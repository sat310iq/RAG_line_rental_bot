"""Decision rules for metrics v2 (Decision Hygiene).

This module implements decision rules based on Decision Hygiene principles:
Step 1: IDMatchRate < 0.9 → Fix evaluation design (don't touch retrieval)
Step 2: Recall@5 < 50% → Retrieval or Corpus issue
Step 3: Completeness < 1.0 → Generation control issue
Step 4: EvidenceBinding < 0.8 → Prompt / Schema / Post-process issue
Step 5: Hallucination.fact_error > 0 → Immediate block
"""

from typing import List, Dict, Any, Optional, Literal
from enum import Enum


class ActionPriority(str, Enum):
    """Action priority levels."""
    CRITICAL = "critical"  # Immediate action required
    HIGH = "high"  # Fix now
    MEDIUM = "medium"  # Monitor
    LOW = "low"  # Defer


class DecisionAction:
    """Represents a decision action item."""
    
    def __init__(
        self,
        step: int,
        condition: str,
        priority: ActionPriority,
        action: str,
        rationale: str,
        affected_questions: Optional[List[str]] = None
    ):
        self.step = step
        self.condition = condition
        self.priority = priority
        self.action = action
        self.rationale = rationale
        self.affected_questions = affected_questions or []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step": self.step,
            "condition": self.condition,
            "priority": self.priority.value,
            "action": self.action,
            "rationale": self.rationale,
            "affected_questions": self.affected_questions,
        }


class DecisionRules:
    """Decision rules engine for metrics v2."""
    
    def __init__(self):
        """Initialize decision rules."""
        self.actions: List[DecisionAction] = []
    
    def evaluate(self, results: List[Dict[str, Any]], aggregate_metrics: Dict[str, Any]) -> List[DecisionAction]:
        """Evaluate results and generate decision actions.
        
        Args:
            results: List of individual evaluation results
            aggregate_metrics: Aggregate metrics dictionary
            
        Returns:
            List of decision actions
        """
        self.actions = []
        
        successful_results = [r for r in results if r.get("success", False)]
        if not successful_results:
            self.actions.append(DecisionAction(
                step=0,
                condition="No successful evaluations",
                priority=ActionPriority.CRITICAL,
                action="Fix evaluation pipeline errors",
                rationale="All evaluations failed. Check RAG pipeline and evaluation setup."
            ))
            return self.actions
        
        # Step 1: ID Normalization Success Rate
        self._check_id_normalization(successful_results, aggregate_metrics)
        
        # Step 2: Recall@5
        self._check_recall(successful_results, aggregate_metrics)
        
        # Step 3: Completeness
        self._check_completeness(successful_results, aggregate_metrics)
        
        # Step 4: Evidence Binding
        self._check_evidence_binding(successful_results, aggregate_metrics)
        
        # Step 5: Hallucination fact_error
        self._check_hallucination_fact_error(successful_results, aggregate_metrics)
        
        return self.actions
    
    def _check_id_normalization(
        self,
        results: List[Dict[str, Any]],
        aggregate_metrics: Dict[str, Any]
    ) -> None:
        """Step 1: Check ID normalization success rate.
        
        Rule: IDMatchRate < 0.9 → Fix evaluation design (don't touch retrieval)
        """
        id_norm_rate = aggregate_metrics.get("avg_id_normalization_success_rate")
        
        if id_norm_rate is None:
            # Check if we have individual results with ID normalization
            id_norm_rates = [r.get("id_normalization_success_rate") for r in results if r.get("id_normalization_success_rate") is not None]
            if id_norm_rates:
                id_norm_rate = sum(id_norm_rates) / len(id_norm_rates)
        
        if id_norm_rate is not None and id_norm_rate < 0.9:
            affected = [
                r.get("question_id", "unknown")
                for r in results
                if r.get("id_normalization_success_rate") is not None
                and r.get("id_normalization_success_rate", 1.0) < 0.9
            ]
            
            self.actions.append(DecisionAction(
                step=1,
                condition=f"ID Normalization Success Rate < 0.9 (current: {id_norm_rate:.2f})",
                priority=ActionPriority.CRITICAL,
                action="Fix evaluation design: Update eval_questions.csv expected IDs or improve ID mapper",
                rationale="Low ID normalization rate indicates evaluation definition issues, not retrieval problems. Do NOT modify retrieval until this is fixed.",
                affected_questions=affected[:10]  # Limit to first 10
            ))
    
    def _check_recall(
        self,
        results: List[Dict[str, Any]],
        aggregate_metrics: Dict[str, Any]
    ) -> None:
        """Step 2: Check Recall@5.
        
        Rule: Recall@5 < 50% → Retrieval or Corpus issue
        """
        recall_at_5 = aggregate_metrics.get("avg_recall_at_5", 0.0)
        
        if recall_at_5 < 0.5:
            # Check if ID normalization is OK (if available)
            id_norm_rate = aggregate_metrics.get("avg_id_normalization_success_rate")
            if id_norm_rate is None:
                id_norm_rates = [r.get("id_normalization_success_rate") for r in results if r.get("id_normalization_success_rate") is not None]
                if id_norm_rates:
                    id_norm_rate = sum(id_norm_rates) / len(id_norm_rates)
            
            if id_norm_rate is None or id_norm_rate >= 0.9:
                # ID normalization is OK, so this is a retrieval issue
                affected = [
                    r.get("question_id", "unknown")
                    for r in results
                    if r.get("recall_at_5") is not None
                    and (r.get("recall_at_5", 0.0) < 0.5)
                ]
                
                self.actions.append(DecisionAction(
                    step=2,
                    condition=f"Recall@5 < 50% (current: {recall_at_5:.1%})",
                    priority=ActionPriority.HIGH,
                    action="Improve retrieval: Check search queries, reranking, or corpus coverage",
                    rationale="Low recall indicates retrieval or corpus issues. Review search strategy and document indexing.",
                    affected_questions=affected[:10]
                ))
    
    def _check_completeness(
        self,
        results: List[Dict[str, Any]],
        aggregate_metrics: Dict[str, Any]
    ) -> None:
        """Step 3: Check Answer Completeness.
        
        Rule: Completeness < 1.0 → Generation control issue
        """
        completeness = aggregate_metrics.get("avg_answer_completeness", 1.0)
        
        if completeness < 1.0:
            affected = [
                r.get("question_id", "unknown")
                for r in results
                if r.get("answer_completeness") is not None
                and r.get("answer_completeness", 1.0) < 1.0
            ]
            
            # Check by question type
            type_breakdown = {}
            for r in results:
                q_type = r.get("question_type", "unknown")
                if q_type not in type_breakdown:
                    type_breakdown[q_type] = []
                if r.get("answer_completeness") is not None and r.get("answer_completeness", 1.0) < 1.0:
                    type_breakdown[q_type].append(r.get("question_id", "unknown"))
            
            rationale = f"Low completeness ({completeness:.2f}) indicates generation control issues. "
            if type_breakdown:
                rationale += f"Affected types: {', '.join(f'{k}({len(v)})' for k, v in type_breakdown.items() if v)}"
            
            self.actions.append(DecisionAction(
                step=3,
                condition=f"Answer Completeness < 1.0 (current: {completeness:.2f})",
                priority=ActionPriority.HIGH,
                action="Improve generation control: Check prompts, schema constraints, or post-processing",
                rationale=rationale,
                affected_questions=affected[:10]
            ))
    
    def _check_evidence_binding(
        self,
        results: List[Dict[str, Any]],
        aggregate_metrics: Dict[str, Any]
    ) -> None:
        """Step 4: Check Evidence Binding Rate.
        
        Rule: EvidenceBinding < 0.8 → Prompt / Schema / Post-process issue
        """
        binding_rate = aggregate_metrics.get("avg_evidence_binding_rate", 1.0)
        
        # Check by question type (different thresholds)
        enumeration_results = [r for r in results if r.get("question_type") == "policy_enumeration"]
        procedure_results = [r for r in results if r.get("question_type") == "procedure"]
        
        if enumeration_results:
            enum_binding = sum(r.get("evidence_binding_rate", 1.0) for r in enumeration_results) / len(enumeration_results)
            if enum_binding < 0.8:
                affected = [
                    r.get("question_id", "unknown")
                    for r in enumeration_results
                    if r.get("evidence_binding_rate", 1.0) < 0.8
                ]
                self.actions.append(DecisionAction(
                    step=4,
                    condition=f"Evidence Binding Rate (enumeration) < 0.8 (current: {enum_binding:.2f})",
                    priority=ActionPriority.MEDIUM,
                    action="Improve citations: Enhance prompt instructions or schema for citation generation",
                    rationale="Low evidence binding for enumeration questions. Citations may be missing from enumerated items.",
                    affected_questions=affected[:10]
                ))
        
        if procedure_results:
            proc_binding = sum(r.get("evidence_binding_rate", 1.0) for r in procedure_results) / len(procedure_results)
            if proc_binding < 0.7:
                affected = [
                    r.get("question_id", "unknown")
                    for r in procedure_results
                    if r.get("evidence_binding_rate", 1.0) < 0.7
                ]
                self.actions.append(DecisionAction(
                    step=4,
                    condition=f"Evidence Binding Rate (procedure) < 0.7 (current: {proc_binding:.2f})",
                    priority=ActionPriority.MEDIUM,
                    action="Improve citations: Enhance prompt instructions or schema for citation generation",
                    rationale="Low evidence binding for procedure questions. Citations may be missing from procedure steps.",
                    affected_questions=affected[:10]
                ))
        
        # Overall check
        if binding_rate < 0.7:
            affected = [
                r.get("question_id", "unknown")
                for r in results
                if r.get("evidence_binding_rate") is not None
                and r.get("evidence_binding_rate", 1.0) < 0.7
            ]
            if not any(a.step == 4 for a in self.actions):  # Avoid duplicate
                self.actions.append(DecisionAction(
                    step=4,
                    condition=f"Evidence Binding Rate < 0.7 (current: {binding_rate:.2f})",
                    priority=ActionPriority.MEDIUM,
                    action="Improve citations: Enhance prompt instructions or schema for citation generation",
                    rationale="Low evidence binding rate indicates missing citations in answers.",
                    affected_questions=affected[:10]
                ))
    
    def _check_hallucination_fact_error(
        self,
        results: List[Dict[str, Any]],
        aggregate_metrics: Dict[str, Any]
    ) -> None:
        """Step 5: Check Hallucination fact_error.
        
        Rule: Hallucination.fact_error > 0 → Immediate block
        """
        fact_error_rate = aggregate_metrics.get("avg_hallucination_fact_error", 0.0)
        
        if fact_error_rate > 0.0:
            affected = [
                r.get("question_id", "unknown")
                for r in results
                if r.get("hallucination_fact_error") is not None
                and r.get("hallucination_fact_error", 0.0) > 0.0
            ]
            
            self.actions.append(DecisionAction(
                step=5,
                condition=f"Hallucination fact_error > 0 (current: {fact_error_rate:.2f})",
                priority=ActionPriority.CRITICAL,
                action="Immediate fix required: Block fact errors. Review prompts, add fact-checking, or implement post-processing",
                rationale="Fact errors are critical safety issues. Answers contain false information that contradicts evidence.",
                affected_questions=affected[:10]
            ))
    
    def get_summary(self) -> Dict[str, Any]:
        """Get decision summary.
        
        Returns:
            Dictionary with summary information
        """
        critical_count = sum(1 for a in self.actions if a.priority == ActionPriority.CRITICAL)
        high_count = sum(1 for a in self.actions if a.priority == ActionPriority.HIGH)
        medium_count = sum(1 for a in self.actions if a.priority == ActionPriority.MEDIUM)
        low_count = sum(1 for a in self.actions if a.priority == ActionPriority.LOW)
        
        return {
            "total_actions": len(self.actions),
            "critical": critical_count,
            "high": high_count,
            "medium": medium_count,
            "low": low_count,
            "actions": [a.to_dict() for a in self.actions],
        }
