from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import dns.rdatatype
import dns.resolver
import dns.query
import dns.zone
import dns.message


class RecordSource(Enum):
    PARENT = auto()
    AUTHORITATIVE = auto()
    LOCAL = auto()

class MigrationState(Enum):
    ANALYZING = auto()      # Initial audit of current TTLs
    REDUCING_TTL = auto()   # Waiting for lower TTLs to propagate
    READY_TO_PIVOT = auto() # All TTLs are low enough for the switch
    MIGRATING = auto()      # Pointing NS to new provider
    CLEANUP = auto()        # Raising TTLs on the new provider

@dataclass(frozen=True)
class DNSRecord:
    source: RecordSource
    name: str
    rtype: str
    ttl: int
    values: List[str]
    observed_at: datetime = field(default_factory=datetime.now)

    @property
    def expires_at(self) -> datetime:
        """The exact timestamp when this cache entry is guaranteed to be stale."""
        return self.observed_at + timedelta(seconds=self.ttl)

    def time_remaining(self) -> timedelta:
        diff = self.expires_at - datetime.now()
        return max(diff, timedelta(0)) # Returns diff if positive otherwise 0

@dataclass(frozen=True)
class MigrationConfig:
    domain: str
    target_ttl: int = 300
    nameservers: List[str] = field(default_factory=list)
    is_verbose: bool = False

class DNSMigrationManager:
    def __init__(self, config: MigrationConfig):
        self.config = config
        self.state = MigrationState.ANALYZING
        self.records: List[DNSRecord] = []

    def _get_nameserver_ips(self) -> List[str]:
        if self.config.nameservers:
            return self.config.nameservers

        try:
            ns_answers = dns.resolver.resolve(self.config.domain, 'NS')
            ips = []
            for ns in ns_answers:
                ip_answers = dns.resolver.resolve(str(ns.target), 'A')
                for ip in ip_answers:
                    ips.append(str(ip))
            return ips
        except Exception:
            return []

    def _get_tld_ns_ips(self) -> List[str]:
        tld = self.config.domain.split('.')[-1]
        try:
            ns_answers = dns.resolver.resolve(tld, 'NS')
            ips = []
            for ns in ns_answers:
                a_answers = dns.resolver.resolve(str(ns.target), 'A')
                for ip in a_answers:
                    ips.append(str(ip))
            return ips
        except Exception:
            return []

    def fetch_parent_records(self):
        tld_ips = self._get_tld_ns_ips()
        for ip in tld_ips:
            try:
                query = dns.message.make_query(self.config.domain, 'NS')
                response = dns.query.udp(query, ip, timeout=2)
                section = response.answer if response.answer else response.authority
                for rrset in section:
                    if rrset.rdtype == dns.rdatatype.NS:
                        record = DNSRecord(
                            source=RecordSource.PARENT,
                            name=str(rrset.name),
                            rtype="NS",
                            ttl=rrset.ttl,
                            values=[str(rdata) for rdata in rrset]
                        )
                        self.records.append(record)
                        return
            except Exception:
                continue

    def fetch_authoritative_records(self):
        ns_ips = self._get_nameserver_ips()
        for ip in ns_ips:
            try:
                query = dns.message.make_query(self.config.domain, 'A')
                response = dns.query.udp(query, ip, timeout=5)
                for rrset in response.answer:
                    if rrset.rdtype == dns.rdatatype.A:
                        record = DNSRecord(
                            source=RecordSource.AUTHORITATIVE,
                            name=str(rrset.name),
                            rtype="A",
                            ttl=rrset.ttl,
                            values=[str(rdata) for rdata in rrset]
                        )
                        self.records.append(record)
                        return
            except Exception:
                continue

    def fetch_local_records(self):
        try:
            answers = dns.resolver.resolve(self.config.domain, "A")
            record = DNSRecord(
                source=RecordSource.LOCAL,
                name=self.config.domain,
                rtype="A",
                ttl=answers.rrset.ttl,
                values=[str(rdata) for rdata in answers]
            )
            self.records.append(record)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            pass

    def is_cache_cleared(self) -> bool:
        return all(r.time_remaining().total_seconds() <= 0 for r in self.records)

    def get_migration_horizon(self) -> Optional[datetime]:
        if not self.records:
            return None
        return max(r.expires_at for r in self.records)
