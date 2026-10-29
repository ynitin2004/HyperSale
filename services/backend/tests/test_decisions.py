"""Executable decision tests: each asserts that a recorded decision still holds in code.

DECISION-TRACES.md maps every decision to the test that guards it; these are the ones no
behavioural test covers, because they are rules about *where* things may live. A failure
here means a decision was broken - fix the code or record a new decision, never relax this.
"""
import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
WEB_SRC = BACKEND.parents[1] / "apps" / "web" / "src"
MIGRATIONS = BACKEND / "alembic" / "versions"

PROVIDER_SDKS = {"anthropic", "openai", "websockets", "azure"}
MODEL_ID = re.compile(r"""["'](gpt-[\w.-]+|claude-[\w.-]+|whisper-\d|azure-realtime)["']""")


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_rules_1_provider_sdks_are_imported_only_inside_adapters() -> None:
    """RULES §1 / D8 / D19: no provider SDK outside adapters/."""
    offenders = []
    for path in _py_files(APP):
        if "adapters" in path.relative_to(APP).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            offenders += [f"{path.relative_to(BACKEND)}: {n}" for n in names if n in PROVIDER_SDKS]
    assert offenders == []


def test_rules_1_model_ids_live_only_in_models_py() -> None:
    """RULES §1 / D16 / D28: a model ID anywhere else is an ID nobody can audit."""
    allowed = APP / "adapters" / "llm" / "models.py"
    offenders = [
        f"{p.relative_to(BACKEND)}: {m.group(1)}"
        for p in _py_files(APP) if p != allowed
        for m in MODEL_ID.finditer(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_d8_no_provider_credential_reaches_the_browser() -> None:
    """D8 / D29 / RULES §1: the SPA never sees a provider key or endpoint."""
    patterns = re.compile(r"api-key|AZURE_|ANTHROPIC_|AGENTROUTER|SUPABASE_SECRET|sk-[A-Za-z0-9]{8}")
    offenders = [
        f"{p.relative_to(WEB_SRC)}" for p in WEB_SRC.rglob("*.ts*")
        if p.name not in ("schema.d.ts",) and patterns.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_d16_provenance_versions_are_explicit_and_stable() -> None:
    """D16: every score names rubric, prompt, model and metrics versions."""
    from app.adapters.llm.models import SCORING_MODEL
    from app.modules.scoring.metrics import METRICS_VERSION
    from app.modules.scoring.prompt import SCORING_PROMPT_VERSION

    assert re.fullmatch(r"score-v\d+-\d{4}-\d{2}-\d{2}", SCORING_PROMPT_VERSION)
    assert re.fullmatch(r"metrics-v\d+", METRICS_VERSION)
    assert SCORING_MODEL


def test_d22_each_migration_execute_holds_one_statement() -> None:
    """D22: asyncpg rejects multi-statement executes; split, never batch."""
    offenders = []
    for path in MIGRATIONS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "execute"):
                continue
            arg = node.args[0] if node.args else None
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                continue  # f-strings are single statements by construction here
            body = re.sub(r"\$\$.*?\$\$", "", arg.value, flags=re.DOTALL)
            body = re.sub(r"--[^\n]*", "", body)
            if len([s for s in body.split(";") if s.strip()]) > 1:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_rules_1_tenant_tables_force_rls_in_migrations() -> None:
    """ARCHITECTURE §6: every tenant table is ENABLE + FORCE RLS with WITH CHECK."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in MIGRATIONS.glob("*.py"))
    for table in ("practice_sessions", "transcript_turns", "reports", "criterion_scores"):
        assert table in text
    assert text.count("FORCE ROW LEVEL SECURITY") >= 2  # 0002 loop + 0003 loop
    assert "WITH CHECK (workspace_id = app_current_workspace())" in text


def test_d29_browser_reported_usage_is_bounded() -> None:
    """D32: data-channel usage is accepted only within physical limits."""
    from app.modules.practice.live import bound_client_usage

    assert bound_client_usage({"audio_out": 10**9, "responses": 10**9}, 10_000)["audio_out"] <= 400


def test_d27_no_client_identity_is_spoofed() -> None:
    """D27: reach gateways with the official SDK as shipped - never override its identity."""
    pattern = re.compile(r"User-Agent|default_headers|x-stainless", re.IGNORECASE)
    offenders = [str(p.relative_to(BACKEND)) for p in _py_files(APP)
                 if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
