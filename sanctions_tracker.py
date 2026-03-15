"""
TITANIUM VANGUARD - Sanctions Tracker
Phase 2B: Tracks sanctions lists from OFAC, EU, UK, and UN.
Detects additions, removals, and modifications to sanctions lists.
"""

import aiohttp
import asyncio
import csv
import io
import json
import xml.etree.ElementTree as ET
import hashlib
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timezone, date
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup, FeatureNotFound

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from collectors.base import BaseCollector
from core.config import get_settings


@dataclass
class SanctionedEntity:
    """Represents a sanctioned entity"""
    name: str
    entity_type: str  # person, organization, vessel, aircraft
    country: Optional[str]
    country_iso: Optional[str]
    sanction_list: str  # OFAC, EU, UK, UN
    sanction_program: Optional[str]
    date_added: date
    reason: Optional[str]
    designating_authority: str
    aliases: Optional[List[str]] = None
    ofac_id: Optional[str] = None
    eu_reference: Optional[str] = None
    un_reference: Optional[str] = None
    raw_data: Optional[dict] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result['date_added'] = self.date_added.isoformat() if self.date_added else None
        return result


# Sanctions list sources
SANCTIONS_SOURCES = {
    "ofac_sdn": {
        "name": "OFAC Specially Designated Nationals (SDN)",
        "url": "https://www.treasury.gov/ofac/downloads/sdn.csv",
        "list_type": "OFAC",
        "format": "csv",
        "authority": "US Treasury"
    },
    "ofac_consolidated": {
        "name": "OFAC Consolidated Non-SDN List",
        "url": "https://www.treasury.gov/ofac/downloads/consolidated/consolidated.csv",
        "list_type": "OFAC",
        "format": "csv",
        "authority": "US Treasury"
    },
    "uk_sanctions": {
        "name": "UK Consolidated Sanctions List",
        "url": "https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/ConList.csv",
        "list_type": "UK",
        "format": "csv",
        "authority": "UK HM Treasury"
    },
    "un_consolidated": {
        "name": "UN Security Council Consolidated List",
        "url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "list_type": "UN",
        "format": "xml",
        "authority": "UN Security Council"
    },
    "eu_sanctions": {
        "name": "EU Consolidated Sanctions List",
        "url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content",
        "list_type": "EU",
        "format": "csv",
        "authority": "European Commission"
    }
}

# Country code mapping for sanctions
COUNTRY_MAPPING = {
    "RUSSIA": "RUS", "RUSSIAN FEDERATION": "RUS",
    "CHINA": "CHN", "PEOPLE'S REPUBLIC OF CHINA": "CHN",
    "IRAN": "IRN", "ISLAMIC REPUBLIC OF IRAN": "IRN",
    "NORTH KOREA": "PRK", "DEMOCRATIC PEOPLE'S REPUBLIC OF KOREA": "PRK", "DPRK": "PRK",
    "SYRIA": "SYR", "SYRIAN ARAB REPUBLIC": "SYR",
    "CUBA": "CUB",
    "VENEZUELA": "VEN",
    "MYANMAR": "MMR", "BURMA": "MMR",
    "BELARUS": "BLR",
    "UKRAINE": "UKR",
    "AFGHANISTAN": "AFG",
    "IRAQ": "IRQ",
    "LIBYA": "LBY",
    "SOMALIA": "SOM",
    "SUDAN": "SDN",
    "SOUTH SUDAN": "SSD",
    "YEMEN": "YEM",
    "ZIMBABWE": "ZWE",
    "LEBANON": "LBN",
    "MALI": "MLI",
    "NICARAGUA": "NIC",
    "ERITREA": "ERI",
    "ETHIOPIA": "ETH",
    "HAITI": "HTI",
}


class SanctionsTracker(BaseCollector):
    """
    Collector for tracking international sanctions lists.
    Monitors OFAC, EU, UK, and UN sanctions for additions and changes.
    """

    def __init__(self, config=None):
        super().__init__(config)
        self.sources = SANCTIONS_SOURCES
        self._valid_country_isos: Optional[Set[str]] = None
        self.timeout = aiohttp.ClientTimeout(total=120)  # Longer timeout for large files
        self.headers = {
            "User-Agent": "TITANIUM-VANGUARD/2.0 (Geopolitical Intelligence System)",
            "Accept": "text/csv,application/xml,*/*",
        }
        self.logger.info(f"SanctionsTracker initialized with {len(self.sources)} sources")

    async def fetch(self) -> List[Dict]:
        """
        Fetch sanctions data from all sources.

        Returns:
            List of raw sanctions data
        """
        all_entities = []

        for source_id, source_config in self.sources.items():
            try:
                entities = await self._fetch_source(source_id, source_config)
                if entities:
                    all_entities.extend(entities)
                    self.logger.info(f"Source {source_id}: fetched {len(entities)} entities")
            except Exception as e:
                self.logger.warning(f"Error fetching {source_id}: {e}")

            # Respectful delay between sources
            await asyncio.sleep(2)

        self.logger.info(f"Total fetched: {len(all_entities)} sanctioned entities")
        return all_entities

    async def _fetch_source(self, source_id: str, source_config: Dict) -> List[Dict]:
        """
        Fetch sanctions data from a single source.

        Args:
            source_id: Source identifier
            source_config: Source configuration

        Returns:
            List of raw entity dictionaries
        """
        entities = []

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    source_config["url"],
                    headers=self.headers,
                    ssl=False
                ) as response:

                    if response.status != 200:
                        self.logger.warning(f"Source {source_id} returned {response.status}")
                        return []

                    content = await response.read()

                    # Parse based on format
                    if source_config["format"] == "csv":
                        entities = self._parse_csv(content, source_config)
                    elif source_config["format"] == "xml":
                        entities = self._parse_xml(content, source_config)
                    elif source_config["format"] == "json":
                        entities = self._parse_json(content, source_config)

        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout fetching {source_id}")
        except aiohttp.ClientError as e:
            self.logger.warning(f"HTTP error fetching {source_id}: {e}")
        except Exception as e:
            self.logger.error(f"Error fetching {source_id}: {e}")

        return entities

    def _parse_csv(self, content: bytes, source_config: Dict) -> List[Dict]:
        """Parse CSV sanctions data"""
        entities = []

        try:
            # Decode content
            text = content.decode("utf-8", errors="ignore")
            reader = csv.DictReader(io.StringIO(text))

            for row in reader:
                try:
                    entity = self._extract_entity_from_csv(row, source_config)
                    if entity:
                        entities.append(entity)
                except Exception as e:
                    self.logger.debug(f"Error parsing CSV row: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error parsing CSV: {e}")

        return entities

    def _extract_entity_from_csv(self, row: Dict, source_config: Dict) -> Optional[Dict]:
        """Extract entity from CSV row based on source type"""
        list_type = source_config["list_type"]

        # Different formats for different sources
        if list_type == "OFAC":
            return self._extract_ofac_entity(row, source_config)
        elif list_type == "UK":
            return self._extract_uk_entity(row, source_config)
        elif list_type == "EU":
            return self._extract_eu_entity(row, source_config)

        return None

    def _extract_ofac_entity(self, row: Dict, source_config: Dict) -> Optional[Dict]:
        """Extract entity from OFAC CSV format"""
        # OFAC SDN format columns
        name = row.get("SDN_Name") or row.get("Name") or row.get("name", "")
        if not name or len(name) < 2:
            return None

        entity_type_raw = row.get("SDN_Type") or row.get("Type") or row.get("type", "")
        entity_type = self._normalize_entity_type(entity_type_raw)

        country = row.get("Country") or row.get("country", "")
        country_iso = self._get_country_iso(country)

        program = row.get("Program") or row.get("program", "")

        return {
            "name": name.strip()[:500],
            "entity_type": entity_type,
            "country": country,
            "country_iso": country_iso,
            "sanction_list": "OFAC",
            "sanction_program": program,
            "designating_authority": source_config["authority"],
            "ofac_id": row.get("Ent_num") or row.get("ent_num"),
            "aliases": self._extract_aliases(row),
            "raw_data": row
        }

    def _extract_uk_entity(self, row: Dict, source_config: Dict) -> Optional[Dict]:
        """Extract entity from UK sanctions CSV format"""
        name = row.get("Name 1") or row.get("name", "")
        if not name or len(name) < 2:
            return None

        # Combine name parts
        name_parts = [row.get(f"Name {i}", "") for i in range(1, 7)]
        full_name = " ".join(part.strip() for part in name_parts if part)

        entity_type_raw = row.get("Group Type") or row.get("type", "Individual")
        entity_type = self._normalize_entity_type(entity_type_raw)

        country = row.get("Country") or row.get("Nationality") or ""
        country_iso = self._get_country_iso(country)

        return {
            "name": full_name[:500],
            "entity_type": entity_type,
            "country": country,
            "country_iso": country_iso,
            "sanction_list": "UK",
            "sanction_program": row.get("Regime") or row.get("regime", ""),
            "designating_authority": source_config["authority"],
            "aliases": self._extract_uk_aliases(row),
            "raw_data": row
        }

    def _extract_eu_entity(self, row: Dict, source_config: Dict) -> Optional[Dict]:
        """Extract entity from EU sanctions CSV format"""
        name = row.get("nameAlias") or row.get("Name") or row.get("name", "")
        if not name or len(name) < 2:
            return None

        entity_type_raw = row.get("subjectType") or row.get("type", "person")
        entity_type = self._normalize_entity_type(entity_type_raw)

        country = row.get("country") or row.get("citizenship") or ""
        country_iso = self._get_country_iso(country)

        return {
            "name": name.strip()[:500],
            "entity_type": entity_type,
            "country": country,
            "country_iso": country_iso,
            "sanction_list": "EU",
            "sanction_program": row.get("programme") or row.get("regulation", ""),
            "designating_authority": source_config["authority"],
            "eu_reference": row.get("euReferenceNumber"),
            "raw_data": row
        }

    def _parse_xml(self, content: bytes, source_config: Dict) -> List[Dict]:
        """Parse XML sanctions data (UN format)"""
        entities = []

        try:
            root = ET.fromstring(content)

            individuals = [
                elem for elem in root.iter()
                if elem.tag.split("}")[-1] == "INDIVIDUAL"
            ]
            for ind in individuals:
                entity = self._extract_un_individual(ind, source_config)
                if entity:
                    entities.append(entity)

            entities_xml = [
                elem for elem in root.iter()
                if elem.tag.split("}")[-1] == "ENTITY"
            ]
            for ent in entities_xml:
                entity = self._extract_un_entity(ent, source_config)
                if entity:
                    entities.append(entity)

            return entities

        except ET.ParseError as e:
            self.logger.warning(f"Error parsing XML (ElementTree): {e}")
        except Exception as e:
            self.logger.error(f"Error parsing XML: {e}")
            return entities

        # Fallback to BeautifulSoup if ElementTree fails
        try:
            try:
                soup = BeautifulSoup(content, "xml")
            except FeatureNotFound:
                soup = BeautifulSoup(content, "html.parser")

            individuals = soup.find_all("INDIVIDUAL")
            for ind in individuals:
                entity = self._extract_un_individual(ind, source_config)
                if entity:
                    entities.append(entity)

            entities_xml = soup.find_all("ENTITY")
            for ent in entities_xml:
                entity = self._extract_un_entity(ent, source_config)
                if entity:
                    entities.append(entity)

        except Exception as e:
            self.logger.error(f"Error parsing XML (BeautifulSoup): {e}")

        return entities

    def _find_text(self, element, tag_name: str) -> Optional[str]:
        """Find text in XML element (ElementTree or BeautifulSoup)."""
        try:
            found = element.find(tag_name)
            if found is not None:
                if hasattr(found, "get_text"):
                    text = found.get_text()
                else:
                    text = found.text
                return text.strip() if text else None
        except Exception:
            pass

        try:
            for child in element.iter():
                if child is element:
                    continue
                if child.tag.split("}")[-1] == tag_name:
                    text = child.text
                    return text.strip() if text else None
        except Exception:
            pass

        return None

    def _extract_un_individual(self, element, source_config: Dict) -> Optional[Dict]:
        """Extract individual from UN XML"""
        try:
            first_name = self._find_text(element, "FIRST_NAME")
            second_name = self._find_text(element, "SECOND_NAME")
            third_name = self._find_text(element, "THIRD_NAME")

            name_parts = [name for name in [first_name, second_name, third_name] if name]

            name = " ".join(name_parts)
            if not name or len(name) < 2:
                return None

            country = self._find_text(element, "NATIONALITY") or ""
            country_iso = self._get_country_iso(country)

            program = self._find_text(element, "UN_LIST_TYPE") or ""
            reference = self._find_text(element, "REFERENCE_NUMBER")

            return {
                "name": name[:500],
                "entity_type": "person",
                "country": country,
                "country_iso": country_iso,
                "sanction_list": "UN",
                "sanction_program": program,
                "designating_authority": source_config["authority"],
                "un_reference": reference,
                "raw_data": {"xml_type": "individual"}
            }
        except Exception as e:
            self.logger.debug(f"Error extracting UN individual: {e}")
            return None

    def _extract_un_entity(self, element, source_config: Dict) -> Optional[Dict]:
        """Extract entity from UN XML"""
        try:
            name = self._find_text(element, "FIRST_NAME") or self._find_text(element, "ENTITY_NAME") or ""

            if not name or len(name) < 2:
                return None

            country = self._find_text(element, "COUNTRY") or ""
            country_iso = self._get_country_iso(country)

            program = self._find_text(element, "UN_LIST_TYPE") or ""
            reference = self._find_text(element, "REFERENCE_NUMBER")

            return {
                "name": name[:500],
                "entity_type": "organization",
                "country": country,
                "country_iso": country_iso,
                "sanction_list": "UN",
                "sanction_program": program,
                "designating_authority": source_config["authority"],
                "un_reference": reference,
                "raw_data": {"xml_type": "entity"}
            }
        except Exception as e:
            self.logger.debug(f"Error extracting UN entity: {e}")
            return None

    def _parse_json(self, content: bytes, source_config: Dict) -> List[Dict]:
        """Parse JSON sanctions data"""
        entities = []

        try:
            data = json.loads(content)
            records = data.get("records", data.get("data", []))

            for record in records:
                entity = {
                    "name": record.get("name", "")[:500],
                    "entity_type": self._normalize_entity_type(record.get("type", "")),
                    "country": record.get("country", ""),
                    "country_iso": self._get_country_iso(record.get("country", "")),
                    "sanction_list": source_config["list_type"],
                    "sanction_program": record.get("program", ""),
                    "designating_authority": source_config["authority"],
                    "raw_data": record
                }
                if entity["name"]:
                    entities.append(entity)

        except Exception as e:
            self.logger.error(f"Error parsing JSON: {e}")

        return entities

    def _normalize_entity_type(self, raw_type: str) -> str:
        """Normalize entity type to standard values"""
        if not raw_type:
            return "person"

        raw_lower = raw_type.lower()

        if any(word in raw_lower for word in ["individual", "person", "human"]):
            return "person"
        elif any(word in raw_lower for word in ["entity", "organization", "company", "corp"]):
            return "organization"
        elif any(word in raw_lower for word in ["vessel", "ship", "boat"]):
            return "vessel"
        elif any(word in raw_lower for word in ["aircraft", "plane", "airplane"]):
            return "aircraft"

        return "person"

    def _get_country_iso(self, country: str) -> Optional[str]:
        """Get ISO country code from country name"""
        if not country:
            return None

        country_upper = country.upper().strip()

        # Direct mapping
        if country_upper in COUNTRY_MAPPING:
            return COUNTRY_MAPPING[country_upper]

        # Check if it's already an ISO code
        if len(country_upper) == 3 and country_upper.isalpha():
            return country_upper

        # Partial match
        for name, iso in COUNTRY_MAPPING.items():
            if name in country_upper or country_upper in name:
                return iso

        return None

    def _load_valid_country_isos(self, session) -> Set[str]:
        """Load valid country ISO codes once per runtime to prevent FK violations."""
        if self._valid_country_isos is None:
            rows = session.execute(text("SELECT iso_code FROM countries")).fetchall()
            self._valid_country_isos = {row[0] for row in rows if row and row[0]}
        return self._valid_country_isos

    def _extract_aliases(self, row: Dict) -> List[str]:
        """Extract aliases from OFAC row"""
        aliases = []

        # Common alias column names
        alias_cols = ["alt", "aka", "alias", "AKA"]
        for col in alias_cols:
            if col in row and row[col]:
                aliases.append(row[col].strip())

        return aliases if aliases else None

    def _extract_uk_aliases(self, row: Dict) -> List[str]:
        """Extract aliases from UK row"""
        aliases = []

        # UK format has numbered alias columns
        for i in range(1, 10):
            alias = row.get(f"Alias {i}") or row.get(f"alias{i}", "")
            if alias:
                aliases.append(alias.strip())

        return aliases if aliases else None

    async def parse(self, raw_data: List[Dict]) -> List[SanctionedEntity]:
        """
        Parse raw sanctions data into SanctionedEntity objects.

        Args:
            raw_data: Raw entity dictionaries

        Returns:
            List of SanctionedEntity objects
        """
        entities = []
        seen_names = set()

        for data in raw_data:
            try:
                name = data.get("name", "")

                # Create unique key to avoid duplicates
                key = f"{name}_{data.get('sanction_list')}"
                if key in seen_names:
                    continue
                seen_names.add(key)

                entity = SanctionedEntity(
                    name=name,
                    entity_type=data.get("entity_type", "person"),
                    country=data.get("country"),
                    country_iso=data.get("country_iso"),
                    sanction_list=data.get("sanction_list", "UNKNOWN"),
                    sanction_program=data.get("sanction_program"),
                    date_added=date.today(),  # Use current date if not provided
                    reason=data.get("reason"),
                    designating_authority=data.get("designating_authority", "Unknown"),
                    aliases=data.get("aliases"),
                    ofac_id=data.get("ofac_id"),
                    eu_reference=data.get("eu_reference"),
                    un_reference=data.get("un_reference"),
                    raw_data=data.get("raw_data")
                )

                entities.append(entity)

            except Exception as e:
                self.logger.warning(f"Error parsing entity: {e}")
                continue

        self.logger.info(f"Parsed {len(entities)} sanctioned entities")
        return entities

    async def save(self, entities: List[SanctionedEntity]) -> int:
        """
        Save sanctioned entities to the database.

        Args:
            entities: List of SanctionedEntity objects

        Returns:
            Number of entities saved
        """
        saved = 0
        changes_detected = []

        try:
            with self.db.session() as session:
                valid_country_isos = self._load_valid_country_isos(session)
                for entity in entities:
                    try:
                        country_iso = entity.country_iso
                        if country_iso and country_iso not in valid_country_isos:
                            self.logger.debug(
                                "Unknown country ISO '%s' for sanctioned entity '%s'; storing NULL",
                                country_iso,
                                entity.name[:80],
                            )
                            country_iso = None

                        with session.begin_nested():
                            # Check if entity already exists
                            result = session.execute(
                                text("""
                                    SELECT id, name FROM sanctioned_entities
                                    WHERE name = :name AND sanction_list = :sanction_list
                                """),
                                {"name": entity.name, "sanction_list": entity.sanction_list}
                            )
                            existing = result.fetchone()

                            if existing:
                                # Entity already exists, skip for now
                                # In production, we'd compare and update
                                continue

                            # Insert new entity
                            session.execute(
                                text("""
                                    INSERT INTO sanctioned_entities (
                                        name, entity_type, country_iso, nationality,
                                        sanction_list, sanction_program, designating_authority,
                                        date_added, aliases, ofac_id, eu_reference, un_reference,
                                        is_active, raw_data
                                    ) VALUES (
                                        :name, :entity_type, :country_iso, :nationality,
                                        :sanction_list, :sanction_program, :designating_authority,
                                        :date_added, :aliases, :ofac_id, :eu_reference, :un_reference,
                                        :is_active, :raw_data
                                    )
                                """),
                                {
                                    "name": entity.name,
                                    "entity_type": entity.entity_type,
                                    "country_iso": country_iso,
                                    "nationality": entity.country,
                                    "sanction_list": entity.sanction_list,
                                    "sanction_program": entity.sanction_program,
                                    "designating_authority": entity.designating_authority,
                                    "date_added": entity.date_added,
                                    "aliases": entity.aliases,
                                    "ofac_id": entity.ofac_id,
                                    "eu_reference": entity.eu_reference,
                                    "un_reference": entity.un_reference,
                                    "is_active": True,
                                    "raw_data": json.dumps(entity.raw_data) if entity.raw_data else None
                                }
                            )

                            # Record the change
                            session.execute(
                                text("""
                                    INSERT INTO sanctions_changes (
                                        entity_name, change_type, sanction_list,
                                        new_data, effective_date
                                    ) VALUES (
                                        :entity_name, :change_type, :sanction_list,
                                        :new_data, :effective_date
                                    )
                                """),
                                {
                                    "entity_name": entity.name,
                                    "change_type": "addition",
                                    "sanction_list": entity.sanction_list,
                                    "new_data": json.dumps(entity.to_dict()),
                                    "effective_date": entity.date_added
                                }
                            )
                        # The nested transaction is committed here if no exception occurred
                        saved += 1
                    except IntegrityError as e:
                        # The 'begin_nested' block handles the rollback to the savepoint automatically.
                        self.logger.warning(
                            f"Skipping entity '{entity.name[:50]}' due to DB integrity error "
                            f"(likely invalid country code '{entity.country_iso}'). Error: {e}"
                        )
                        continue  # Continue to the next entity

                session.commit()

                self.logger.info(f"Saved {saved} sanctioned entities")

        except Exception as e:
            self.logger.error(f"Error in save: {e}")

        return saved

    async def validate(self, entity) -> bool:
        """Validate a sanctioned entity"""
        if not hasattr(entity, 'name') or not entity.name or len(entity.name) < 2:
            return False
        if not hasattr(entity, 'sanction_list') or not entity.sanction_list:
            return False
        return True

    async def detect_sanctions_changes(self) -> Dict:
        """
        Detect changes in sanctions lists compared to previous data.

        Returns:
            Dict with additions, removals, and modifications
        """
        from sqlalchemy import text

        try:
            # Fetch current data from sources
            current_entities = await self.fetch()
            current_names = {(e.get("name", ""), e.get("sanction_list", "")): e for e in current_entities}

            # Get stored entities
            with self.db.session() as session:
                result = session.execute(
                    text("SELECT name, sanction_list FROM sanctioned_entities WHERE is_active = TRUE")
                )
                stored = {(row[0], row[1]) for row in result.fetchall()}

            # Detect changes
            current_keys = set(current_names.keys())
            additions = current_keys - stored
            removals = stored - current_keys

            return {
                "additions": len(additions),
                "removals": len(removals),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": {
                    "new_entities": list(additions)[:50],  # Limit to 50
                    "removed_entities": list(removals)[:50]
                }
            }

        except Exception as e:
            self.logger.error(f"Error detecting changes: {e}")
            return {"error": str(e)}

    async def check_entity_match(self, name: str, threshold: float = 0.85) -> List[Dict]:
        """
        Check if a name matches any sanctioned entities.

        Args:
            name: Name to check
            threshold: Fuzzy match threshold (0-1)

        Returns:
            List of matching entities
        """
        from sqlalchemy import text

        matches = []

        try:
            with self.db.session() as session:
                # Exact match first
                result = session.execute(
                    text("""
                        SELECT name, entity_type, country_iso, sanction_list, sanction_program
                        FROM sanctioned_entities
                        WHERE is_active = TRUE
                          AND (name ILIKE :pattern OR :name = ANY(aliases))
                    """),
                    {"name": name, "pattern": f"%{name}%"}
                )

                for row in result.fetchall():
                    matches.append({
                        "name": row[0],
                        "entity_type": row[1],
                        "country_iso": row[2],
                        "sanction_list": row[3],
                        "sanction_program": row[4],
                        "match_type": "exact"
                    })

        except Exception as e:
            self.logger.error(f"Error checking entity match: {e}")

        return matches

    async def run(self) -> Dict:
        """Execute the full collection pipeline"""
        try:
            self.logger.info(f"Starting {self.name}...")
            start_time = datetime.now(timezone.utc)

            # Fetch
            raw_data = await self.fetch()
            self.logger.info(f"Fetched {len(raw_data)} raw entities")

            # Parse
            entities = await self.parse(raw_data)
            self.logger.info(f"Parsed {len(entities)} entities")

            # Validate
            valid_entities = [e for e in entities if await self.validate(e)]
            self.logger.info(f"Validated {len(valid_entities)}/{len(entities)} entities")

            # Save
            saved = await self.save(valid_entities)

            # Stats
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.last_run = datetime.now(timezone.utc)
            self.events_collected = saved

            # Count by list
            list_counts = {}
            for e in valid_entities:
                list_counts[e.sanction_list] = list_counts.get(e.sanction_list, 0) + 1

            stats = {
                "collector": self.name,
                "status": "success",
                "sources_processed": len(self.sources),
                "raw_fetched": len(raw_data),
                "parsed": len(entities),
                "valid": len(valid_entities),
                "saved": saved,
                "by_list": list_counts,
                "elapsed_seconds": round(elapsed, 2),
                "timestamp": self.last_run.isoformat()
            }

            self.logger.info(f"{self.name} completed: {saved} entities saved")
            return stats

        except Exception as e:
            self.logger.error(f"Error in run: {e}", exc_info=True)
            self.last_error = str(e)
            return {
                "collector": self.name,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }


# Convenience function
async def main():
    """Test the collector"""
    tracker = SanctionsTracker()
    result = await tracker.run()
    print(f"Collection result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
