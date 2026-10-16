"""One entry per agent: prompt file, role, whether it needs the language policy, output schema."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    role: str            # STAGE or AUDITOR
    prompt_file: str     # under prompts/agents/
    schema_file: str     # under schemas/
    uses_language_policy: bool = False


_SPECS = [
    AgentSpec("A02-SP", "Scope & Perspective", "STAGE", "A02-SP_Scope_Perspective.md", "A02-SP.schema.json"),
    AgentSpec("A03-LM", "Literature Mining", "STAGE", "A03-LM_Literature_Mining.md", "A03-LM.schema.json"),
    AgentSpec("A04-CQ", "Corpus Qualification", "STAGE", "A04-CQ_Corpus_Qualification.md", "A04-CQ.schema.json"),
    AgentSpec("A05-KE", "Knowledge Extraction", "STAGE", "A05-KE_Knowledge_Extraction.md", "A05-KE.schema.json"),
    AgentSpec("A06-SV", "Scientific Validation", "AUDITOR", "A06-SV_Scientific_Validation.md", "A06-SV.schema.json"),
    AgentSpec("A07-SYN", "Synthesis & Gap Analysis", "STAGE", "A07-SYN_Synthesis.md", "A07-SYN.schema.json"),
    AgentSpec("A08-OL", "Outline & Display Planning", "STAGE", "A08-OL_Outline.md", "A08-OL.schema.json"),
    AgentSpec("A09-WRI", "Writing", "STAGE", "A09-WRI_Writing.md", "A09-WRI.schema.json", True),
    AgentSpec("A10-RV", "Verification", "AUDITOR", "A10-RV_Verification.md", "A10-RV.schema.json", True),
    AgentSpec("A11-RC", "Critique & Readability", "AUDITOR", "A11-RC_Critique.md", "A11-RC.schema.json", True),
    AgentSpec("A12-EDI", "Editing", "STAGE", "A12-EDI_Editing.md", "A12-EDI.schema.json", True),
]

AGENTS: dict[str, AgentSpec] = {s.agent_id: s for s in _SPECS}
