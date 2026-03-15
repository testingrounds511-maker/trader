"""
TITANIUM VANGUARD - Base Collector
Clase base abstracta para todos los collectors
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Optional
import asyncio
import logging

from core.config import get_settings
from core.logger import get_logger
from core.database import Database
from models import Event


class BaseCollector(ABC):
    """
    Clase base abstracta para collectors de datos geopolíticos
    Define la interfaz que todos los collectors deben implementar
    """
    
    def __init__(self, config=None):
        """
        Inicializa el collector base
        
        Args:
            config: Settings instance (si no se proporciona, usa get_settings())
        """
        self.config = config or get_settings()
        self.logger = get_logger(self.__class__.__name__)
        self.db = Database()
        self.name = self.__class__.__name__
        self.last_run = None
        self.last_error = None
        self.events_collected = 0
    
    @abstractmethod
    async def fetch(self) -> List[Dict]:
        """
        Obtiene datos crudos de la fuente
        
        Returns:
            List[Dict]: Datos crudos sin procesar
        
        Raises:
            NotImplementedError: Debe ser implementado por subclass
        """
        pass
    
    @abstractmethod
    async def parse(self, raw_data: List[Dict]) -> List[Event]:
        """
        Parsea datos crudos a objetos Event
        
        Args:
            raw_data: Datos crudos de fetch()
        
        Returns:
            List[Event]: Eventos parseados
        
        Raises:
            NotImplementedError: Debe ser implementado por subclass
        """
        pass
    
    async def validate(self, event: Event) -> bool:
        """
        Valida que un evento sea correcto
        
        Args:
            event: Event object a validar
        
        Returns:
            bool: True si es válido, False si no
        """
        try:
            # Validaciones básicas
            if not event.id:
                self.logger.warning(f"Event sin ID: {event.title}")
                return False
            
            if not event.title:
                self.logger.warning(f"Event {event.id} sin título")
                return False
            
            if not event.event_date:
                self.logger.warning(f"Event {event.id} sin fecha")
                return False
            
            if event.relevance_score < 0 or event.relevance_score > 1:
                self.logger.warning(f"Event {event.id} relevance inválido: {event.relevance_score}")
                return False
            
            return True
        
        except Exception as e:
            self.logger.error(f"Error validando event {event.id}: {e}")
            return False
    
    async def save(self, events: List[Event]) -> int:
        """
        Guarda eventos en la base de datos
        
        Args:
            events: Lista de eventos a guardar
        
        Returns:
            int: Número de eventos guardados exitosamente
        """
        saved = 0
        
        try:
            with self.db.session() as session:
                for event in events:
                    try:
                        # Verificar si el evento ya existe
                        existing = session.query(Event).filter(Event.id == event.id).first()
                        
                        if existing:
                            self.logger.debug(f"Event {event.id} ya existe, saltando")
                            continue
                        
                        session.add(event)
                        saved += 1
                    
                    except Exception as e:
                        self.logger.error(f"Error guardando event {event.id}: {e}")
                        continue
            
            self.logger.info(f"Guardados {saved} eventos")
            return saved
        
        except Exception as e:
            self.logger.error(f"Error en save(): {e}")
            return 0
    
    async def run(self) -> Dict:
        """
        Ejecuta el pipeline completo: fetch -> parse -> validate -> save
        
        Returns:
            Dict: Estadísticas de la ejecución
        """
        try:
            self.logger.info(f"Iniciando {self.name}...")
            start_time = datetime.utcnow()
            
            # Fetch
            self.logger.debug("Fetching datos...")
            raw_data = await self.fetch()
            self.logger.info(f"Obtenidos {len(raw_data)} elementos crudos")
            
            # Parse
            self.logger.debug("Parseando datos...")
            events = await self.parse(raw_data)
            self.logger.info(f"Parseados {len(events)} eventos")
            
            # Validate
            self.logger.debug("Validando eventos...")
            valid_events = []
            for event in events:
                if await self.validate(event):
                    valid_events.append(event)
            
            self.logger.info(f"Validados {len(valid_events)}/{len(events)} eventos")
            
            # Save
            self.logger.debug("Guardando eventos...")
            saved = await self.save(valid_events)
            
            # Estadísticas
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            self.last_run = datetime.utcnow()
            self.events_collected = saved
            
            stats = {
                "collector": self.name,
                "status": "success",
                "raw_data": len(raw_data),
                "parsed": len(events),
                "valid": len(valid_events),
                "saved": saved,
                "elapsed_seconds": elapsed,
                "timestamp": self.last_run.isoformat(),
            }
            
            self.logger.info(f"{self.name} completado: {stats}")
            return stats
        
        except Exception as e:
            self.logger.error(f"Error en run(): {e}", exc_info=True)
            self.last_error = str(e)
            return {
                "collector": self.name,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }
    
    def get_status(self) -> Dict:
        """
        Obtiene el estado actual del collector
        
        Returns:
            Dict: Información de estado
        """
        return {
            "name": self.name,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "events_collected": self.events_collected,
            "last_error": self.last_error,
            "is_running": False,  # Se actualizaría si estuviera corriendo
        }
    
    async def retry_with_backoff(
        self,
        func,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        *args,
        **kwargs
    ):
        """
        Ejecuta una función con reintentos y backoff exponencial
        
        Args:
            func: Función async a ejecutar
            max_attempts: Máximo número de intentos
            initial_delay: Delay inicial en segundos
            backoff_factor: Factor multiplicador del delay
            *args, **kwargs: Argumentos para la función
        
        Returns:
            Resultado de la función si tiene éxito
        
        Raises:
            Exception: Si todos los intentos fallan
        """
        delay = initial_delay
        
        for attempt in range(max_attempts):
            try:
                return await func(*args, **kwargs)
            
            except Exception as e:
                if attempt == max_attempts - 1:
                    self.logger.error(f"Falló después de {max_attempts} intentos: {e}")
                    raise
                
                self.logger.warning(
                    f"Intento {attempt + 1} falló, reintentando en {delay}s: {e}"
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
