# Pre-change literal contract audit

Literal presence is not semantic equivalence; rows marked no require explicit hardening. Local evidence/coverage validators additionally apply.

| Schema/mode | JSON path | Rule | Value | In prior prompt | Risk |
|---|---|---|---|---|---|
| A07-SYN.bounded-final.schema.json | $ | required | ["agent_id", "prompt_version", "mode", "status", "warnings", "limitations", "thesis_options", "proposed_interpretations", "beyond_prose_bindings"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.agent_id | const | "A07-SYN" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.prompt_version | const | "1.0" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.mode | const | "FINAL" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_EVIDENCE"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.warnings | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.warnings[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.warnings[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.limitations | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.limitations[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.limitations[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options | maxItems | 3 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[] | required | ["option_id", "type", "text", "title_draft", "contribution_statement_draft", "proposition_ids"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.thesis_options[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].option_id | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].option_id | maxLength | 40 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].option_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].type | enum | ["CONCLUSION_THESIS", "ORGANIZING_THESIS"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].text | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].text | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].text | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].title_draft | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].title_draft | maxLength | 160 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].title_draft | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].contribution_statement_draft | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].contribution_statement_draft | maxLength | 320 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].contribution_statement_draft | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].proposition_ids | maxItems | 24 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].proposition_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].proposition_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].proposition_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.thesis_options[].proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[] | required | ["pi_id", "kind", "statement", "what_it_goes_beyond", "premise_proposition_ids"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].pi_id | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].pi_id | maxLength | 40 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].pi_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].kind | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].kind | maxLength | 80 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].kind | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].statement | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].statement | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].statement | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].what_it_goes_beyond | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].what_it_goes_beyond | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].what_it_goes_beyond | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].premise_proposition_ids | maxItems | 24 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].premise_proposition_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].premise_proposition_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].premise_proposition_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.proposed_interpretations[].premise_proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[] | required | ["surface", "proposition_ids"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].surface | minLength | 1 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].surface | maxLength | 80 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].surface | type | "string" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].proposition_ids | maxItems | 24 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].proposition_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].proposition_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].proposition_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-final.schema.json | $.beyond_prose_bindings[].proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $ | required | ["agent_id", "prompt_version", "mode", "status", "warnings", "limitations", "propositions", "knowledge_gaps", "findings_not_used", "retrieval_requests"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.agent_id | const | "A07-SYN" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.prompt_version | const | "1.0" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.mode | const | "GROUP" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_EVIDENCE"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.warnings | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.warnings[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.warnings[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.limitations | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.limitations[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.limitations[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions | maxItems | 12 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[] | required | ["type", "assertion", "evidence", "source_item_ids", "satisfies", "prominence"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].type | enum | ["SOURCE_GROUNDED", "CLAIM_APPRAISAL", "THEME_GROUNDED", "REPORTING_ONLY_INTEGRATION"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].assertion | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].assertion | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].assertion | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence | maxItems | 24 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[] | required | ["finding_id", "role"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].finding_id | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].finding_id | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].finding_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].role | enum | ["SUPPORTING", "CONFLICTING", "SUBJECT_OF_APPRAISAL"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal | required | ["statement", "claim_source_record_id", "a06_rationale"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.statement | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.statement | maxLength | 600 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.statement | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.claim_source_record_id | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.claim_source_record_id | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.claim_source_record_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.a06_rationale | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.a06_rationale | maxLength | 1200 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.propositions[].evidence[].appraisal.a06_rationale | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].source_item_ids | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].source_item_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].source_item_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].source_item_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].source_item_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].satisfies | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].satisfies | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].satisfies[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].satisfies[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].satisfies[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.propositions[].prominence | enum | ["HEADLINE", "NARRATIVE_PRIMARY", "NARRATIVE_SUPPORTING", "DISPLAY", "SUPPLEMENTARY"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps | maxItems | 16 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[] | required | ["type", "statement", "source_item_ids", "established_by", "satisfies"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].type | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].type | maxLength | 60 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].type | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].statement | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].statement | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].statement | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].source_item_ids | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].source_item_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].source_item_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].source_item_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].source_item_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].established_by | maxItems | 24 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].established_by | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].established_by[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].established_by[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].established_by[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].satisfies | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].satisfies | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].satisfies[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].satisfies[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.knowledge_gaps[].satisfies[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used | maxItems | 24 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[] | required | ["finding_id", "reason"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[].finding_id | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[].finding_id | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[].finding_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[].reason | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[].reason | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.findings_not_used[].reason | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests | maxItems | 4 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[] | required | [] | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[].finding_ids | maxItems | 12 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[].finding_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[].finding_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[].finding_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[].finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[].query | maxLength | 160 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-group.schema.json | $.retrieval_requests[].query | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $ | required | ["agent_id", "prompt_version", "mode", "status", "warnings", "limitations", "theme_change_proposals", "scope_drift", "fivew1h"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-plan.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-plan.schema.json | $.agent_id | const | "A07-SYN" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.prompt_version | const | "1.0" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.mode | const | "PLAN" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_EVIDENCE"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-plan.schema.json | $.warnings | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.warnings[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.warnings[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.limitations | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.limitations[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.limitations[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[] | required | ["proposal", "rationale", "finding_ids"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].proposal | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].proposal | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].proposal | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].rationale | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].rationale | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].rationale | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].finding_ids | maxItems | 12 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].finding_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].finding_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].finding_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.theme_change_proposals[].finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.scope_drift | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.scope_drift | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.scope_drift[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.scope_drift[] | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.scope_drift[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h | maxItems | 9 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[] | required | ["theme_id", "unresolved"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[].theme_id | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[].theme_id | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[].theme_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[].unresolved | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[].unresolved | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-plan.schema.json | $.fivew1h[].unresolved | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $ | required | ["agent_id", "prompt_version", "mode", "status", "warnings", "limitations", "reviews", "issues", "retrieval_requests"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.agent_id | const | "A07-SYN" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.prompt_version | const | "1.0" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.mode | const | "RECONCILE" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_EVIDENCE"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.warnings | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.warnings[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.warnings[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.limitations | maxItems | 8 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.limitations[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.limitations[] | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.reviews | maxItems | 32 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.reviews | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[] | required | ["proposition_id", "outcome", "rationale"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[].proposition_id | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[].proposition_id | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[].proposition_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[].outcome | enum | ["NO_CONFLICT_IDENTIFIED", "ISSUES_IDENTIFIED"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[].rationale | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[].rationale | maxLength | 240 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.reviews[].rationale | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues | maxItems | 32 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.issues | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[] | required | ["kind", "proposition_ids", "finding_ids", "limitation"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.issues[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].kind | enum | ["UNRESOLVED_CONTRADICTION", "CONTEXT_DEPENDENT", "SHARED_EVIDENCE", "DUPLICATE_PUBLICATION", "UNSUPPORTED_INTERPRETATION"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].proposition_ids | maxItems | 12 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].proposition_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].proposition_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].proposition_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].finding_ids | maxItems | 24 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].finding_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].finding_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].finding_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].limitation | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].limitation | maxLength | 480 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.issues[].limitation | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests | maxItems | 4 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[] | required | [] | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[].finding_ids | maxItems | 12 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[].finding_ids | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[].finding_ids[] | minLength | 1 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[].finding_ids[] | maxLength | 120 | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[].finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[].query | maxLength | 160 | no / not explicit | contract mismatch or rejection |
| A07-SYN.bounded-reconcile.schema.json | $.retrieval_requests[].query | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "mode", "knowledge_gaps", "proposed_interpretations", "thesis_options", "beyond_prose_bindings"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.final.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.final.schema.json | $.agent_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.prompt_version | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.final.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.mode | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.propositions | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.knowledge_gaps | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.knowledge_gaps[] | required | ["gap_id", "statement", "satisfies"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.final.schema.json | $.knowledge_gaps[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.final.schema.json | $.proposed_interpretations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.thesis_options | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.final.schema.json | $.beyond_prose_bindings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "mode", "propositions", "context_contrasts", "findings_context", "findings_not_used"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.group.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.group.schema.json | $.agent_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.prompt_version | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.group.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.mode | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.propositions | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.group.schema.json | $.propositions[] | required | ["proposition_id", "type", "assertion", "satisfies"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.group.schema.json | $.propositions[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.group.schema.json | $.context_contrasts | type | "array" | no / not explicit | contract mismatch or rejection |
| A07-SYN.group.schema.json | $.findings_context | type | "array" | no / not explicit | contract mismatch or rejection |
| A07-SYN.group.schema.json | $.findings_not_used | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "mode", "fivew1h", "groups", "findings_not_used"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.plan.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.plan.schema.json | $.agent_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.prompt_version | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.plan.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.mode | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.fivew1h | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.groups | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.plan.schema.json | $.groups[] | required | ["group_id", "kind", "name", "basis", "finding_ids"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.plan.schema.json | $.groups[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.plan.schema.json | $.findings_not_used | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "package_version", "fivew1h", "propositions", "groups", "knowledge_gaps", "proposed_interpretations", "thesis_options", "coverage_realization", "researcher_decision"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A07-SYN.schema.json | $.agent_id | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.prompt_version | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A07-SYN.schema.json | $.warnings | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.limitations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.package_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A07-SYN.schema.json | $.fivew1h | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.propositions | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.groups | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.knowledge_gaps | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.proposed_interpretations | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.thesis_options | type | "array" | yes (literal only) | local validation still required |
| A07-SYN.schema.json | $.coverage_realization | type | "array" | no / not explicit | contract mismatch or rejection |
| A07-SYN.schema.json | $.researcher_decision | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "plan_version", "title", "abstract_plan", "keywords", "writing_order", "sections", "allocation_ledger", "display_items", "budget_summary", "readability"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.agent_id | type | "string" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.prompt_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.limitations[] | type | "string" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.plan_version | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.title | required | ["text", "proposition_ids"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.title | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.title.text | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.title.word_count | type | "integer" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.title.proposition_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.title.proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.abstract_plan | required | ["target_words", "ordered_proposition_ids", "contribution_statement"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.abstract_plan | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.abstract_plan.target_words | type | "integer" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.abstract_plan.ordered_proposition_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.abstract_plan.ordered_proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.abstract_plan.contribution_statement | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.keywords | maxItems | 6 | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.keywords | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.keywords[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.writing_order | minItems | 1 | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.writing_order | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.writing_order[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections | minItems | 1 | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[] | required | ["section_id", "level", "heading", "heading_kind", "heading_proposition_ids", "purpose", "word_budget", "theme_ids", "ordered_items", "display_item_ids", "transition_in", "transition_out", "wording_restrictions"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].section_id | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].level | type | "integer" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].heading | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].heading_kind | enum | ["DESCRIPTIVE", "CLAIM_BEARING", "REPORTING_ONLY", "RELATIONSHIP_UNRESOLVED"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].heading_proposition_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].heading_proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].purpose | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].word_budget | type | "integer" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].theme_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].theme_ids[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].ordered_items | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].ordered_items[] | required | ["item_id", "item_type", "group", "note_to_writer"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].ordered_items[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].ordered_items[].item_id | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].ordered_items[].item_type | enum | ["PROPOSITION", "GAP", "AUTHOR_INTERPRETATION"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].ordered_items[].group | type | ["string", "null"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].ordered_items[].note_to_writer | type | ["string", "null"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].display_item_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].display_item_ids[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].transition_in | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].transition_out | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.sections[].wording_restrictions | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.sections[].wording_restrictions[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.allocation_ledger | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.allocation_ledger[] | required | ["item_id", "outcome", "section_id", "grouped_with", "reason"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.allocation_ledger[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.allocation_ledger[].item_id | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.allocation_ledger[].outcome | enum | ["DISCUSSED", "GROUPED_WITH", "TABLE_ONLY", "NOT_INDIVIDUALLY_DISCUSSED"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.allocation_ledger[].section_id | type | ["string", "null"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.allocation_ledger[].grouped_with | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.allocation_ledger[].grouped_with[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.allocation_ledger[].reason | type | ["string", "null"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.display_items | maxItems | 1 | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.display_items | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.display_items[] | required | ["display_id", "type", "placement_section_id", "purpose"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.display_items[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.display_items[].display_id | const | "T1" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.display_items[].type | const | "TABLE_COMPARISON" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.display_items[].placement_section_id | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.display_items[].purpose | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.budget_summary | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability | required | ["background_concepts", "abbreviations", "nomenclature"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.background_concepts | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.background_concepts[] | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.readability.abbreviations | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.abbreviations[] | required | ["abbr", "expansion"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.abbreviations[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.abbreviations[].abbr | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.readability.abbreviations[].expansion | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.readability.nomenclature | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.nomenclature[] | required | ["entity", "form_to_use", "alternative_at_first_mention"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.nomenclature[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.readability.nomenclature[].entity | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.readability.nomenclature[].form_to_use | type | "string" | yes (literal only) | local validation still required |
| A08-OL.schema.json | $.readability.nomenclature[].alternative_at_first_mention | type | ["string", "null"] | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.reserved_human_items | type | "array" | no / not explicit | contract mismatch or rejection |
| A08-OL.schema.json | $.reserved_human_items[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "mode", "title", "abstract", "keywords", "table_captions"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.agent_id | type | "string" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.prompt_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.mode | const | "FRONT_MATTER" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.title | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.abstract | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.keywords | maxItems | 6 | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.keywords | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.keywords[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.table_captions | maxItems | 1 | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.table_captions | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.table_captions[] | required | ["display_id", "caption"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.table_captions[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.front.schema.json | $.table_captions[].display_id | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.front.schema.json | $.table_captions[].caption | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "draft_version", "title", "abstract", "keywords", "sections", "figure_legends", "main_text_word_count", "plan_gaps"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.agent_id | type | "string" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.prompt_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.schema.json | $.draft_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.title | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.schema.json | $.abstract | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.schema.json | $.keywords | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.sections | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.figure_legends | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.main_text_word_count | type | "integer" | no / not explicit | contract mismatch or rejection |
| A09-WRI.schema.json | $.plan_gaps | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "mode", "section", "retrieval_requests", "plan_gaps", "ceiling_unclear"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.agent_id | type | "string" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.prompt_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_EVIDENCE", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.warnings[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.mode | const | "SECTION" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.section/anyOf0 | required | ["section_id", "heading", "text_markdown", "word_count"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.section/anyOf0 | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.section/anyOf0.section_id | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.section/anyOf0.heading | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.section/anyOf0.text_markdown | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.section/anyOf0.word_count | type | "integer" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.section/anyOf1 | type | "null" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.retrieval_requests | maxItems | 4 | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.retrieval_requests | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.retrieval_requests[] | required | ["element_ids", "finding_ids", "reason"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.retrieval_requests[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.retrieval_requests[].element_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.retrieval_requests[].element_ids[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.retrieval_requests[].finding_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.retrieval_requests[].finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.retrieval_requests[].reason | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.plan_gaps | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.plan_gaps[] | required | ["gap_marker", "section_id", "missing", "why_needed"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.plan_gaps[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.plan_gaps[].gap_marker | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.plan_gaps[].section_id | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.plan_gaps[].missing | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.plan_gaps[].why_needed | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.ceiling_unclear | type | "array" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.ceiling_unclear[] | required | ["proposition_id", "question"] | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.ceiling_unclear[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A09-WRI.section.schema.json | $.ceiling_unclear[].proposition_id | type | "string" | yes (literal only) | local validation still required |
| A09-WRI.section.schema.json | $.ceiling_unclear[].question | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $ | required | ["agent_id", "prompt_version", "mode", "status", "verdicts", "issues", "retrieval_requests", "inventory_fingerprint", "reviewed_index_ids"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.agent_id | const | "A10-RV" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.prompt_version | const | "2.0" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.mode | enum | ["LOCAL", "GLOBAL"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.status | enum | ["COMPLETE", "NEEDS_EVIDENCE"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.inventory_fingerprint | maxLength | 64 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.inventory_fingerprint | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.reviewed_index_ids | maxItems | 1000 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.reviewed_index_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.reviewed_index_ids[] | maxLength | 160 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.reviewed_index_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts | maxItems | 12 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[] | required | ["occurrence_id", "verdict", "rationale", "checks", "appraisal_checks", "evidence_finding_ids", "source_item_ids"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].occurrence_id | maxLength | 80 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].occurrence_id | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].verdict | enum | ["VERIFIED", "DEFECT", "UNRESOLVED", "NON_SCIENTIFIC"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].rationale | minLength | 1 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].rationale | maxLength | 240 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].rationale | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].checks | maxItems | 10 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].checks | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].checks[] | enum | ["SOURCE", "NUMBERS_UNITS", "MECHANISM_CAUSALITY", "CERTAINTY", "CHEMICAL_IDENTITY", "MODEL_GBM", "CLINICAL_REACH", "COUNTER_EVIDENCE", "ATTRIBUTION_INDEPENDENCE", "CITATION"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].evidence_finding_ids | maxItems | 24 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].evidence_finding_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].evidence_finding_ids[] | maxLength | 120 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].evidence_finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].source_item_ids | maxItems | 16 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].source_item_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].source_item_ids[] | maxLength | 120 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].source_item_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].appraisal_checks | maxItems | 24 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].appraisal_checks | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].appraisal_checks[] | required | ["binding_id", "preserved"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].appraisal_checks[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.verdicts[].appraisal_checks[].binding_id | maxLength | 240 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].appraisal_checks[].binding_id | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.verdicts[].appraisal_checks[].preserved | type | "boolean" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues | maxItems | 24 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[] | required | ["occurrence_ids", "finding_ids", "code", "severity", "rationale", "correction"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[].occurrence_ids | minItems | 1 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].occurrence_ids | maxItems | 24 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].occurrence_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[].occurrence_ids[] | maxLength | 80 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[].occurrence_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].finding_ids | maxItems | 24 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].finding_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[].finding_ids[] | maxLength | 120 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[].finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].code | minLength | 1 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].code | maxLength | 80 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[].code | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].severity | enum | ["MINOR", "MAJOR", "BLOCKING"] | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.issues[].rationale | minLength | 1 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].rationale | maxLength | 240 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].rationale | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].correction | minLength | 1 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].correction | maxLength | 360 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.issues[].correction | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests | maxItems | 4 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].finding_ids | maxItems | 12 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests[].finding_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].finding_ids[] | maxLength | 120 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].finding_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests[].query | minLength | 1 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests[].query | maxLength | 160 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].query | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests[].source_item_ids | maxItems | 12 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests[].source_item_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].source_item_ids[] | maxLength | 120 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].source_item_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests[].proposition_ids | maxItems | 12 | yes (literal only) | local validation still required |
| A10-RV.bounded.schema.json | $.retrieval_requests[].proposition_ids | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].proposition_ids[] | maxLength | 160 | no / not explicit | contract mismatch or rejection |
| A10-RV.bounded.schema.json | $.retrieval_requests[].proposition_ids[] | type | "string" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "pass", "coverage", "findings", "verification_execution", "finding_severity"] | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.agent_id | type | "string" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $.prompt_version | type | "string" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.warnings[] | type | "string" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.limitations[] | type | "string" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.pass | enum | ["DRAFT", "REVISION", "FINAL"] | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.coverage | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.findings | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.verification_execution | type | "string" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.finding_severity | type | "string" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.detail_requests | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.detail_requests[] | required | ["finding_id", "kind", "check"] | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.detail_requests[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.detail_requests[].finding_id | type | "string" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $.detail_requests[].assertion_excerpt | type | "string" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.detail_requests[].reason | type | "string" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $.detail_requests[].kind | enum | ["UNCITED_CONFLICT", "MISSING_FROM_SCOPE"] | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.detail_requests[].check | type | "string" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $.appraisal_checks | type | "array" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.appraisal_checks[] | required | ["binding_id", "preserved"] | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.appraisal_checks[] | type | "object" | no / not explicit | contract mismatch or rejection |
| A10-RV.schema.json | $.appraisal_checks[].binding_id | type | "string" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $.appraisal_checks[].preserved | type | "boolean" | yes (literal only) | local validation still required |
| A10-RV.schema.json | $.appraisal_checks[].rationale | type | "string" | yes (literal only) | local validation still required |
| A11-RC.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "manuscript_version", "reader_passes", "strengths", "concerns", "decision", "decision_rationale"] | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.agent_id | type | "string" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.prompt_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.warnings[] | type | "string" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A11-RC.schema.json | $.manuscript_version | type | "string" | yes (literal only) | local validation still required |
| A11-RC.schema.json | $.reader_passes | type | "object" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.strengths | type | "array" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.concerns | type | "array" | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.decision | enum | ["ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "HOLD_FOR_UPSTREAM_REVIEW", "INCOMPLETE_CRITIQUE"] | no / not explicit | contract mismatch or rejection |
| A11-RC.schema.json | $.decision_rationale | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "mode", "output_manuscript_version", "title", "abstract", "sections", "change_log", "queries", "escalations"] | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.agent_id | type | "string" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.prompt_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.warnings[] | type | "string" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.schema.json | $.mode | enum | ["REVISION", "LINE", "PROOF", "INTEGRATION"] | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.output_manuscript_version | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.schema.json | $.title | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.schema.json | $.abstract | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.schema.json | $.sections | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.change_log | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.queries | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.schema.json | $.escalations | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $ | required | ["agent_id", "prompt_version", "status", "warnings", "limitations", "mode", "unit", "output_manuscript_version", "change_log", "queries", "escalations"] | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $ | type | "object" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.agent_id | type | "string" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.prompt_version | type | "string" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.status | enum | ["COMPLETE", "COMPLETE_WITH_WARNINGS", "NEEDS_HUMAN_INPUT", "ABSTAINED", "FAILED"] | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.warnings | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.warnings[] | type | "string" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.limitations | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.limitations[] | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.unit.schema.json | $.mode | enum | ["REVISION", "LINE", "PROOF", "INTEGRATION"] | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.output_manuscript_version | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.unit.schema.json | $.title | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.unit.schema.json | $.abstract | type | "string" | yes (literal only) | local validation still required |
| A12-EDI.unit.schema.json | $.sections | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.change_log | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.queries | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.escalations | type | "array" | no / not explicit | contract mismatch or rejection |
| A12-EDI.unit.schema.json | $.unit | type | "string" | yes (literal only) | local validation still required |
