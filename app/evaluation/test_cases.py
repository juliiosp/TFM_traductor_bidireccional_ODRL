"""Fixed evaluation suite and deterministic expectations for each case."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExpectedConstraint:
    """Constraint expected in a generated rule.

    ``right_operand`` stores the semantic value rather than its JSON-LD encoding.
    Dates are compared by calendar date, so both an ``xsd:date`` value and a full
    ``xsd:dateTime`` value for that date are accepted.
    """

    left_operand: str
    operator: str
    right_operand: str


@dataclass(frozen=True)
class ExpectedRule:
    """Core ODRL elements expected for one atomic rule."""

    kind: str
    action: str
    target: str
    assigner: str | None = None
    assignee: str | None = None
    constraints: tuple[ExpectedConstraint, ...] = ()
    duty_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationTestCase:
    id: str
    natural_language: str
    rule_type: str
    main_constraint: str
    policy_type: str = "Set"
    expected_actions: list[str] = field(default_factory=list)
    covered_elements: list[str] = field(default_factory=list)
    expected_rules: tuple[ExpectedRule, ...] = ()
    notes: str = ""


C = ExpectedConstraint
R = ExpectedRule

# The 20 cases cover the supported ODRL subset described in section 3.6.1.
# ``covered_elements`` describes the planned/expected coverage of the suite;
# generated conformance is measured separately by deterministic comparison and
# SHACL validation.
DEFAULT_EVALUATION_CASES: list[EvaluationTestCase] = [
    EvaluationTestCase(
        id="P01",
        natural_language="CompanyA may use Dataset1 only for research purposes.",
        rule_type="Permission",
        main_constraint="Purpose equality",
        policy_type="Set",
        expected_actions=["use"],
        covered_elements=["Set", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "use", "Dataset1", assignee="CompanyA", constraints=(C("purpose", "eq", "research"),)),),
        notes="Permiso básico con restricción de finalidad. Evalúa purpose eq research.",
    ),
    EvaluationTestCase(
        id="P02",
        natural_language="DataProviderA grants ResearchLabA permission to read Dataset2.",
        rule_type="Permission",
        main_constraint="No restriction",
        policy_type="Agreement",
        expected_actions=["read"],
        covered_elements=["Agreement", "permission", "target", "assigner", "assignee", "action"],
        expected_rules=(R("permission", "read", "Dataset2", "DataProviderA", "ResearchLabA"),),
        notes="Acuerdo simple con assigner y assignee explícitos. No implica validez contractual.",
    ),
    EvaluationTestCase(
        id="P03",
        natural_language="DataProviderB offers permission to display Image1 only in Spain.",
        rule_type="Permission",
        main_constraint="Spatial equality",
        policy_type="Offer",
        expected_actions=["display"],
        covered_elements=["Offer", "permission", "target", "assigner", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "display", "Image1", assigner="DataProviderB", constraints=(C("spatial", "eq", "Spain"),)),),
        notes="Oferta simple. Evalúa Offer y spatial eq Spain.",
    ),
    EvaluationTestCase(
        id="P04",
        natural_language="ResearchLabB requests permission to use Dataset3 from 2026-01-01.",
        rule_type="Permission",
        main_constraint="Temporal greater than or equal",
        policy_type="Request",
        expected_actions=["use"],
        covered_elements=["Request", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "use", "Dataset3", assignee="ResearchLabB", constraints=(C("dateTime", "gteq", "2026-01-01"),)),),
        notes="Solicitud de uso. Evalúa Request y dateTime gteq 2026-01-01.",
    ),
    EvaluationTestCase(
        id="P05",
        natural_language="DataProviderC grants CompanyC permission to distribute Report1 if CompanyC attributes DataProviderC.",
        rule_type="Permission with duty",
        main_constraint="Duty",
        policy_type="Agreement",
        expected_actions=["distribute", "attribute"],
        covered_elements=["Agreement", "permission", "duty", "target", "assigner", "assignee", "action"],
        expected_rules=(R("permission", "distribute", "Report1", "DataProviderC", "CompanyC", duty_actions=("attribute",)),),
        notes="Permiso condicionado a una obligación de atribución.",
    ),
    EvaluationTestCase(
        id="P06",
        natural_language="CompanyD must delete Dataset4 within 30 days.",
        rule_type="Obligation",
        main_constraint="Elapsed time",
        policy_type="Set",
        expected_actions=["delete"],
        covered_elements=["Set", "obligation", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("obligation", "delete", "Dataset4", assignee="CompanyD", constraints=(C("elapsedTime", "lteq", "P30D"),)),),
        notes="Obligación independiente con límite temporal relativo.",
    ),
    EvaluationTestCase(
        id="P07",
        natural_language="CompanyE must not modify Software1.",
        rule_type="Prohibition",
        main_constraint="No restriction",
        policy_type="Set",
        expected_actions=["modify"],
        covered_elements=["Set", "prohibition", "target", "assignee", "action"],
        expected_rules=(R("prohibition", "modify", "Software1", assignee="CompanyE"),),
        notes="Prohibición simple sin restricciones.",
    ),
    EvaluationTestCase(
        id="P08",
        natural_language="UserA must not use Document1 for commercial purposes.",
        rule_type="Prohibition",
        main_constraint="Purpose equality",
        policy_type="Set",
        expected_actions=["use"],
        covered_elements=["Set", "prohibition", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("prohibition", "use", "Document1", assignee="UserA", constraints=(C("purpose", "eq", "commercial"),)),),
        notes="Prohibición con purpose eq commercial.",
    ),
    EvaluationTestCase(
        id="P09",
        natural_language="CompanyF may print Document2 fewer than 5 times.",
        rule_type="Permission",
        main_constraint="Count strictly less than",
        policy_type="Set",
        expected_actions=["print"],
        covered_elements=["Set", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "print", "Document2", assignee="CompanyF", constraints=(C("count", "lt", "5"),)),),
        notes="Permiso con count lt 5.",
    ),
    EvaluationTestCase(
        id="P10",
        natural_language="CompanyG may use Dataset5 until 2026-12-31.",
        rule_type="Permission",
        main_constraint="Temporal less than or equal",
        policy_type="Set",
        expected_actions=["use"],
        covered_elements=["Set", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "use", "Dataset5", assignee="CompanyG", constraints=(C("dateTime", "lteq", "2026-12-31"),)),),
        notes="Permiso con dateTime lteq 2026-12-31.",
    ),
    EvaluationTestCase(
        id="P11",
        natural_language="CompanyH must not sell Dataset6.",
        rule_type="Prohibition",
        main_constraint="No restriction",
        policy_type="Set",
        expected_actions=["sell"],
        covered_elements=["Set", "prohibition", "target", "assignee", "action"],
        expected_rules=(R("prohibition", "sell", "Dataset6", assignee="CompanyH"),),
        notes="Prohibición de venta sin restricciones adicionales.",
    ),
    EvaluationTestCase(
        id="P12",
        natural_language="UserB may copy Document3 for personal backup purposes.",
        rule_type="Permission",
        main_constraint="Purpose equality",
        policy_type="Set",
        expected_actions=["copy"],
        covered_elements=["Set", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "copy", "Document3", assignee="UserB", constraints=(C("purpose", "eq", "personal backup"),)),),
        notes="Permiso de copia con finalidad personal de respaldo.",
    ),
    EvaluationTestCase(
        id="P13",
        natural_language="CompanyI must archive Dataset7 for audit purposes.",
        rule_type="Obligation",
        main_constraint="Purpose equality",
        policy_type="Set",
        expected_actions=["archive"],
        covered_elements=["Set", "obligation", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("obligation", "archive", "Dataset7", assignee="CompanyI", constraints=(C("purpose", "eq", "audit"),)),),
        notes="Obligación con finalidad asociada.",
    ),
    EvaluationTestCase(
        id="P14",
        natural_language="ResearchGroupC may derive works from Dataset8 for academic purposes.",
        rule_type="Permission",
        main_constraint="Purpose equality",
        policy_type="Set",
        expected_actions=["derive"],
        covered_elements=["Set", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "derive", "Dataset8", assignee="ResearchGroupC", constraints=(C("purpose", "eq", "academic"),)),),
        notes="Permiso para crear obras derivadas con finalidad académica.",
    ),
    EvaluationTestCase(
        id="P15",
        natural_language="CompanyJ may extract anonymized statistics from Dataset9 strictly after 2026-06-01.",
        rule_type="Permission",
        main_constraint="Temporal strictly greater than",
        policy_type="Set",
        expected_actions=["extract"],
        covered_elements=["Set", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "extract", "Dataset9", assignee="CompanyJ", constraints=(C("dateTime", "gt", "2026-06-01"),)),),
        notes="Permiso con dateTime gt 2026-06-01.",
    ),
    EvaluationTestCase(
        id="P16",
        natural_language="CompanyK may transform Video2 into a lower-resolution format outside France.",
        rule_type="Permission",
        main_constraint="Spatial not equal",
        policy_type="Set",
        expected_actions=["transform"],
        covered_elements=["Set", "permission", "target", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "transform", "Video2", assignee="CompanyK", constraints=(C("spatial", "neq", "France"),)),),
        notes="Permiso con spatial neq France.",
    ),
    EvaluationTestCase(
        id="P17",
        natural_language="DataProviderD grants CompanyL permission to use Dataset10 for educational purposes until 2027-03-31.",
        rule_type="Permission",
        main_constraint="Multiple simple constraints",
        policy_type="Agreement",
        expected_actions=["use"],
        covered_elements=["Agreement", "permission", "target", "assigner", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "use", "Dataset10", "DataProviderD", "CompanyL", (C("purpose", "eq", "educational"), C("dateTime", "lteq", "2027-03-31"))),),
        notes="Dos restricciones simples: purpose eq educational y dateTime lteq 2027-03-31.",
    ),
    EvaluationTestCase(
        id="P18",
        natural_language="DataProviderE grants CompanyM permission to read Dataset11 and prohibits CompanyM from distributing Dataset11.",
        rule_type="Permission and prohibition",
        main_constraint="No restriction",
        policy_type="Agreement",
        expected_actions=["read", "distribute"],
        covered_elements=["Agreement", "permission", "prohibition", "target", "assigner", "assignee", "action"],
        expected_rules=(R("permission", "read", "Dataset11", "DataProviderE", "CompanyM"), R("prohibition", "distribute", "Dataset11", "DataProviderE", "CompanyM")),
        notes="Caso mixto: permite leer y prohíbe distribuir.",
    ),
    EvaluationTestCase(
        id="P19",
        natural_language="DataProviderF grants CompanyN permission to use Dataset12 for commercial purposes if CompanyN compensates DataProviderF.",
        rule_type="Permission with duty",
        main_constraint="Purpose and duty",
        policy_type="Agreement",
        expected_actions=["use", "compensate"],
        covered_elements=["Agreement", "permission", "duty", "target", "assigner", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "use", "Dataset12", "DataProviderF", "CompanyN", (C("purpose", "eq", "commercial"),), ("compensate",)),),
        notes="Permiso con finalidad comercial y duty de compensación.",
    ),
    EvaluationTestCase(
        id="P20",
        natural_language="DataProviderG offers CompanyO permission to access API1 no more than 100 times.",
        rule_type="Permission",
        main_constraint="Count less than or equal",
        policy_type="Offer",
        expected_actions=["read"],
        covered_elements=["Offer", "permission", "target", "assigner", "assignee", "action", "constraint", "leftOperand", "operator", "rightOperand"],
        expected_rules=(R("permission", "read", "API1", "DataProviderG", "CompanyO", (C("count", "lteq", "100"),)),),
        notes="Oferta con count lteq 100 y mapeo de access a read.",
    ),
]
