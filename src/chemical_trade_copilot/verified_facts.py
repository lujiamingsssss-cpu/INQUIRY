from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerifiedThermalFact:
    product: str
    source_file: str
    page_number: int
    name: str
    value: str
    unit: str
    conditions: str
    test_method: str
    curing_agent: str
    mix_ratio: str
    cure_schedule: str


VERIFIED_THERMAL_FACTS = (
    VerifiedThermalFact(
        product="EPON Resin 8280",
        source_file="TDS - Hexion EPON Resin 8280 - Rev 2016.pdf",
        page_number=3,
        name="Heat Deflection Temperature",
        value="156",
        unit="°C",
        conditions="MPDA-cured unfilled casting",
        test_method="ASTM D648",
        curing_agent="Metaphenylenediamine (MPDA)",
        mix_ratio="EPON Resin 8280 100 pbw : MPDA 14.4 pbw",
        cure_schedule="2 h/80°C + 2 h/150°C",
    ),
)
