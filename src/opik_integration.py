"""OPIK integration for Comet logging (optional).

This module provides optional integration with Comet/OPIK for logging
evaluation results. It is only used when ENABLE_COMET_LOGGING=true.

Supports both Comet ML (comet_ml.Experiment) and OPIK SDK (opik.Opik) for logging.
"""

import os
from typing import Dict, List, Any, Optional

from src.config import Config
from src.metrics import match_tier_to_code


class OpikIntegration:
    """OPIK integration for Comet logging."""
    
    def __init__(self, config: Config, force_enable: bool = False):
        """Initialize OPIK integration.
        
        Args:
            config: Application configuration
            force_enable: If True, enable OPIK even if enable_comet_logging is False
                         (useful for chat logging which uses enable_chat_opik_logging)
        """
        self.config = config
        # Enable if either enable_comet_logging is True OR force_enable is True
        self.enabled = config.enable_comet_logging or force_enable
        
        # Comet ML experiment (for backward compatibility)
        self.experiment = None
        
        # OPIK client (for OPIK UI integration)
        self.opik_client = None
        
        if not self.enabled:
            return
        
        # Initialize Comet ML experiment (for Comet ML UI)
        if config.comet_api_key:
            try:
                from comet_ml import Experiment
                self.experiment = Experiment(
                    api_key=config.comet_api_key,
                    project_name=config.comet_project_name,
                    workspace=config.comet_workspace,
                    auto_param_logging=False,
                    auto_metric_logging=False,
                )
                print(f"Comet experiment initialized: {config.comet_project_name}")
            except Exception as e:
                print(f"Warning: Failed to initialize Comet experiment: {e}")
                self.experiment = None
        
        # Initialize OPIK client (for OPIK UI)
        try:
            import opik
            import os
            
            # Set environment variable for project name to avoid "Default Project"
            # This ensures OPIK uses the correct project name even if configure() is called elsewhere
            os.environ['OPIK_PROJECT_NAME'] = config.comet_project_name
            
            # Configure OPIK with API key and workspace
            # Note: project_name is set via environment variable to avoid "Default Project"
            opik.configure(
                api_key=config.comet_api_key,  # OPIK uses same API key as Comet ML
                workspace=config.comet_workspace,
            )
            self.opik_client = opik.Opik(
                project_name=config.comet_project_name,  # Explicitly set project name
                workspace=config.comet_workspace,
                api_key=config.comet_api_key,
            )
            # Store dataset and experiment names for OPIK UI
            self.opik_dataset_name = f"{config.comet_project_name}_eval_dataset"
            self.opik_experiment_name = None  # Will be set when first result is logged
            print(f"OPIK client initialized for project: {config.comet_project_name}")
        except ImportError:
            print("Warning: opik package not installed. OPIK UI logging will be disabled.")
            self.opik_client = None
        except Exception as e:
            print(f"Warning: Failed to initialize OPIK client: {e}")
            self.opik_client = None
    
    def log_evaluation_result(self, result: Dict[str, Any], experiment_type: str = "eval") -> None:
        """Log a single evaluation result to Comet ML and OPIK.
        
        Args:
            result: Evaluation result dictionary
            experiment_type: Type of experiment ("eval" for evaluation script, "chat" for chat bot)
        """
        # Store experiment type for naming
        self._experiment_type = experiment_type
        eval_meta = result.get("_eval_meta") or {}
        trace_kind = (
            eval_meta.get("eval_mode")
            or os.getenv("OPIK_TRACE_KIND")
            or ("offline_eval" if experiment_type == "eval" else "production_chat")
        )
        result["_opik_trace_kind"] = trace_kind
        
        # Log to Comet ML (for Comet ML UI)
        if self.enabled and self.experiment:
            self._log_to_comet_ml(result)
        
        # Log to OPIK (for OPIK UI)
        if self.enabled and self.opik_client:
            self._log_to_opik(result)
    
    def _log_to_comet_ml(self, result: Dict[str, Any]) -> None:
        """Log evaluation result to Comet ML.
        
        Args:
            result: Evaluation result dictionary
        """
        if not self.experiment:
            return
        
        try:
            question_id = result.get("question_id", "unknown")
            # Extract step number from question_id (e.g., "Q001" -> 1)
            try:
                step = int(question_id.replace("Q", "").replace("q", ""))
            except (ValueError, AttributeError):
                step = 0
            
                # Log metrics with step for time-series tracking
            if result.get("success", False):
                # Question type (for conditional metrics)
                question_type = result.get("question_type", "unknown")
                
                # Core retrieval metrics (only if not None)
                recall_at_5 = result.get("recall_at_5")
                if recall_at_5 is not None:
                    self.experiment.log_metric("recall_at_5", recall_at_5, step=step)
                    # Typed recall
                    if question_type != "unknown":
                        self.experiment.log_metric(f"recall_at_5.{question_type}", recall_at_5, step=step)
                recall_at_10 = result.get("recall_at_10")
                if recall_at_10 is not None:
                    self.experiment.log_metric("recall_at_10", recall_at_10, step=step)
                    if question_type != "unknown":
                        self.experiment.log_metric(f"recall_at_10.{question_type}", recall_at_10, step=step)
                mrr = result.get("mrr")
                if mrr is not None:
                    self.experiment.log_metric("mrr", mrr, step=step)
                hit_at_1 = result.get("hit_at_1")
                if hit_at_1 is not None:
                    self.experiment.log_metric("hit_at_1", hit_at_1, step=step)
                
                # Evaluation metrics
                id_norm_rate = result.get("id_normalization_success_rate")
                if id_norm_rate is not None:
                    self.experiment.log_metric("id_normalization_success_rate", id_norm_rate, step=step)
                multi_source_coverage = result.get("multi_source_coverage")
                if multi_source_coverage is not None:
                    self.experiment.log_metric("multi_source_coverage", multi_source_coverage, step=step)
                
                # Generation metrics
                completeness = result.get("answer_completeness")
                if completeness is not None:
                    self.experiment.log_metric("answer_completeness", completeness, step=step)
                evidence_binding = result.get("evidence_binding_rate")
                if evidence_binding is not None:
                    self.experiment.log_metric("evidence_binding_rate", evidence_binding, step=step)
                over_summary = result.get("over_summarization_rate")
                if over_summary is not None:
                    self.experiment.log_metric("over_summarization_rate", over_summary, step=step)
                
                # Safety metrics v2 (decomposed hallucination)
                self.experiment.log_metric("relevance", result.get("relevance", 0.0), step=step)
                self.experiment.log_metric("hallucination_fact_error", result.get("hallucination_fact_error", 0.0), step=step)
                self.experiment.log_metric("hallucination_unsourced_claim", result.get("hallucination_unsourced_claim", 0.0), step=step)
                self.experiment.log_metric("hallucination_overreach", result.get("hallucination_overreach", 0.0), step=step)
                self.experiment.log_metric("fact_error_rate", result.get("hallucination_fact_error", 0.0), step=step)
                u = result.get("hallucination_unsourced_claim", 0.0)
                o = result.get("hallucination_overreach", 0.0)
                self.experiment.log_metric("unsupported_content_rate", max(u, o), step=step)
                # Legacy compatibility (prefer fact_error_rate / decomposed hallucination metrics)
                self.experiment.log_metric("hallucination", result.get("hallucination", 0.0), step=step)
                
                # Rule-based metrics (as binary 0/1)
                self.experiment.log_metric("contains_pii", 1.0 if result.get("contains_pii", False) else 0.0, step=step)
                self.experiment.log_metric(
                    "pii_true_leak_suspected",
                    1.0 if result.get("pii_true_leak_suspected", False) else 0.0,
                    step=step,
                )
                self.experiment.log_metric(
                    "pii_policy_allowed_contact",
                    1.0 if result.get("pii_policy_allowed_contact", False) else 0.0,
                    step=step,
                )
                self.experiment.log_metric(
                    "pii_false_positive_prone",
                    1.0 if result.get("pii_false_positive_prone", False) else 0.0,
                    step=step,
                )
                mt = result.get("match_tier")
                if mt:
                    self.experiment.log_metric("match_tier_code", float(match_tier_to_code(mt)), step=step)
                self.experiment.log_metric("mentions_prohibited", 1.0 if result.get("mentions_prohibited", False) else 0.0, step=step)
                # Typed prohibited mention
                if question_type == "policy_confirmation":
                    self.experiment.log_metric("mentions_prohibited.confirmation", 1.0 if result.get("mentions_prohibited.confirmation", False) else 0.0, step=step)
                elif question_type == "policy_enumeration":
                    self.experiment.log_metric("mentions_prohibited.enumeration", 1.0 if result.get("mentions_prohibited.enumeration", False) else 0.0, step=step)
                
                # Log question details as text with metadata (including question_type)
                self.experiment.log_text(
                    f"Question: {result.get('question', '')}\n"
                    f"Answer: {result.get('answer_text', '')}\n"
                    f"Retrieved IDs: {result.get('retrieved_ids', [])}\n"
                    f"Expected IDs: {result.get('expected_doc_ids', [])}",
                    step=step,
                    metadata={
                        "question_id": question_id,
                        "category": result.get("category", ""),
                        "question_type": question_type,
                        "success": True,
                        "trace_kind": result.get("_opik_trace_kind", ""),
                    }
                )
                
                # Add question_type as tag
                tags = [f"trace:{result.get('_opik_trace_kind', 'unknown')}"]
                if question_type != "unknown":
                    tags.append(f"question_type:{question_type}")
                self.experiment.add_tags(tags)
            else:
                # Log error
                self.experiment.log_metric("success", 0.0, step=step)
                self.experiment.log_text(
                    f"Question: {result.get('question', '')}\n"
                    f"Error: {result.get('error', 'Unknown error')}",
                    step=step,
                    metadata={"question_id": question_id, "success": False}
                )
        except Exception as e:
            print(f"Warning: Failed to log result to Comet ML: {e}")
    
    def _log_to_opik(self, result: Dict[str, Any]) -> None:
        """Log evaluation result to OPIK UI using experiments API.
        
        This method accumulates results and logs them in bulk for efficiency.
        Dataset items are added first, then experiment items reference them by UUID.
        
        Args:
            result: Evaluation result dictionary
        """
        if not self.opik_client:
            return
        
        # Initialize experiment items list and dataset item map if needed
        if not hasattr(self, '_opik_experiment_items'):
            self._opik_experiment_items = []
            self._opik_dataset_item_map = {}  # Maps question_id -> dataset_item_id (UUID)
        
        try:
            # Create or get dataset on first call
            if not hasattr(self, '_opik_dataset'):
                try:
                    self._opik_dataset = self.opik_client.get_or_create_dataset(
                        name=self.opik_dataset_name,
                        description="RAG evaluation dataset"
                    )
                except Exception as e:
                    print(f"Warning: Failed to get/create OPIK dataset: {e}")
                    return
            
            # Create experiment on first result
            if self.opik_experiment_name is None:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                experiment_type = getattr(self, '_experiment_type', 'eval')
                if experiment_type == "chat":
                    self.opik_experiment_name = f"rag_chat_{timestamp}"
                    eval_type = "interactive_chat"
                else:
                    self.opik_experiment_name = f"rag_eval_{timestamp}"
                    eval_type = "rag_system"
                try:
                    experiment = self.opik_client.create_experiment(
                        dataset_name=self.opik_dataset_name,
                        name=self.opik_experiment_name,
                        experiment_config={
                            "model": self.config.openai_model,
                            "evaluation_type": eval_type,
                        }
                    )
                    print(f"OPIK experiment created: {self.opik_experiment_name}")
                except Exception as e:
                    print(f"Warning: Failed to create OPIK experiment: {e}")
                    return
            
            # Prepare experiment item for OPIK
            if result.get("success", False):
                question_id = result.get("question_id", "unknown")
                
                # Add item to dataset if not already added
                if question_id not in self._opik_dataset_item_map:
                    try:
                        # Insert item into dataset
                        items_to_insert = [{
                            "input": result.get("question", ""),
                            "expected_output": result.get("expected_answer", ""),
                            "metadata": {
                                "question_id": question_id,
                                "category": result.get("category", ""),
                                "question_type": result.get("question_type", "unknown"),
                                "match_tier": result.get("match_tier", "unknown"),
                            }
                        }]
                        self._opik_dataset.insert(items_to_insert)
                        
                        # Get the inserted item's UUID by querying the dataset
                        # Get recent items (the one we just inserted should be among them)
                        all_items = self._opik_dataset.get_items()
                        # Find the item we just inserted by matching input/question
                        question_text = result.get("question", "")
                        for item in all_items:
                            if item.get("input") == question_text:
                                self._opik_dataset_item_map[question_id] = item["id"]
                                break
                        
                        # Fallback: if not found, we'll need to handle this differently
                        if question_id not in self._opik_dataset_item_map:
                            print(f"Warning: Could not find UUID for question_id {question_id} after insert")
                            return
                    except Exception as e:
                        print(f"Warning: Failed to add item to OPIK dataset: {e}")
                        return
                
                # Get UUID for this question
                dataset_item_id = self._opik_dataset_item_map[question_id]
                
                # Create feedback scores from metrics v2 (skip None values)
                feedback_scores = []
                question_type = result.get("question_type", "unknown")
                
                # Retrieval metrics
                if "recall_at_5" in result and result.get("recall_at_5") is not None:
                    feedback_scores.append({
                        "name": "recall_at_5",
                        "value": result.get("recall_at_5", 0.0),
                        "source": "sdk"
                    })
                if "recall_at_10" in result and result.get("recall_at_10") is not None:
                    feedback_scores.append({
                        "name": "recall_at_10",
                        "value": result.get("recall_at_10", 0.0),
                        "source": "sdk"
                    })
                if "hit_at_1" in result and result.get("hit_at_1") is not None:
                    feedback_scores.append({
                        "name": "hit_at_1",
                        "value": result.get("hit_at_1", 0.0),
                        "source": "sdk"
                    })
                if "mrr" in result and result.get("mrr") is not None:
                    feedback_scores.append({
                        "name": "mrr",
                        "value": result.get("mrr", 0.0),
                        "source": "sdk"
                    })
                
                # Evaluation metrics
                if "id_normalization_success_rate" in result and result.get("id_normalization_success_rate") is not None:
                    feedback_scores.append({
                        "name": "id_normalization_success_rate",
                        "value": result.get("id_normalization_success_rate", 0.0),
                        "source": "sdk"
                    })
                if "multi_source_coverage" in result and result.get("multi_source_coverage") is not None:
                    feedback_scores.append({
                        "name": "multi_source_coverage",
                        "value": result.get("multi_source_coverage", 0.0),
                        "source": "sdk"
                    })
                
                # Generation metrics
                if "answer_completeness" in result and result.get("answer_completeness") is not None:
                    feedback_scores.append({
                        "name": "answer_completeness",
                        "value": result.get("answer_completeness", 0.0),
                        "source": "sdk"
                    })
                if "evidence_binding_rate" in result and result.get("evidence_binding_rate") is not None:
                    feedback_scores.append({
                        "name": "evidence_binding_rate",
                        "value": result.get("evidence_binding_rate", 0.0),
                        "source": "sdk"
                    })
                if "over_summarization_rate" in result and result.get("over_summarization_rate") is not None:
                    feedback_scores.append({
                        "name": "over_summarization_rate",
                        "value": result.get("over_summarization_rate", 0.0),
                        "source": "sdk"
                    })
                
                # Safety metrics v2
                if "relevance" in result and result.get("relevance") is not None:
                    feedback_scores.append({
                        "name": "relevance",
                        "value": result.get("relevance", 0.0),
                        "source": "sdk"
                    })
                if "hallucination_fact_error" in result:
                    feedback_scores.append({
                        "name": "hallucination_fact_error",
                        "value": result.get("hallucination_fact_error", 0.0),
                        "source": "sdk"
                    })
                if "hallucination_unsourced_claim" in result:
                    feedback_scores.append({
                        "name": "hallucination_unsourced_claim",
                        "value": result.get("hallucination_unsourced_claim", 0.0),
                        "source": "sdk"
                    })
                if "hallucination_overreach" in result:
                    feedback_scores.append({
                        "name": "hallucination_overreach",
                        "value": result.get("hallucination_overreach", 0.0),
                        "source": "sdk"
                    })
                # Legacy compatibility
                if "hallucination" in result and result.get("hallucination") is not None:
                    feedback_scores.append({
                        "name": "hallucination",
                        "value": result.get("hallucination", 0.0),
                        "source": "sdk"
                    })
                if "hallucination_fact_error" in result:
                    feedback_scores.append({
                        "name": "fact_error_rate",
                        "value": result.get("hallucination_fact_error", 0.0),
                        "source": "sdk"
                    })
                u = result.get("hallucination_unsourced_claim", 0.0)
                o = result.get("hallucination_overreach", 0.0)
                feedback_scores.append({
                    "name": "unsupported_content_rate",
                    "value": max(u, o),
                    "source": "sdk"
                })

                mt_str = result.get("match_tier")
                feedback_scores.append({
                    "name": "match_tier_code",
                    "value": float(match_tier_to_code(mt_str)),
                    "source": "sdk",
                })
                if result.get("recall_at_5_strict") is not None:
                    feedback_scores.append({
                        "name": "recall_at_5_strict",
                        "value": float(result.get("recall_at_5_strict", 0.0)),
                        "source": "sdk",
                    })
                feedback_scores.append({
                    "name": "pii_true_leak_suspected",
                    "value": 1.0 if result.get("pii_true_leak_suspected", False) else 0.0,
                    "source": "sdk",
                })
                feedback_scores.append({
                    "name": "pii_policy_allowed_contact",
                    "value": 1.0 if result.get("pii_policy_allowed_contact", False) else 0.0,
                    "source": "sdk",
                })
                feedback_scores.append({
                    "name": "pii_false_positive_prone",
                    "value": 1.0 if result.get("pii_false_positive_prone", False) else 0.0,
                    "source": "sdk",
                })
                feedback_scores.append({
                    "name": "semantic_neighbor_hit",
                    "value": 1.0 if result.get("semantic_neighbor_hit", False) else 0.0,
                    "source": "sdk",
                })
                
                # Add to batch for bulk logging (using UUID)
                experiment_item = {
                    "dataset_item_id": dataset_item_id,
                    "evaluate_task_result": {
                        "prediction": result.get("answer_text", ""),
                    },
                    "feedback_scores": feedback_scores,
                    "metadata": {
                        "match_tier": mt_str or "unknown",
                        "question_id": str(question_id),
                    },
                }
                
                # Add thread_id to metadata if present (for chat sessions)
                thread_id = result.get("thread_id")
                if thread_id:
                    experiment_item["metadata"]["thread_id"] = thread_id
                
                self._opik_experiment_items.append(experiment_item)
        except Exception as e:
            print(f"Warning: Failed to prepare OPIK log entry: {e}")
    
    def _flush_opik_items(self) -> None:
        """Flush accumulated OPIK experiment items to the server."""
        if not self.opik_client or not hasattr(self, '_opik_experiment_items'):
            return
        
        if not self._opik_experiment_items or self.opik_experiment_name is None:
            return
        
        try:
            # Log experiment items in bulk
            self.opik_client.rest_client.experiments.experiment_items_bulk(
                experiment_name=self.opik_experiment_name,
                dataset_name=self.opik_dataset_name,
                items=self._opik_experiment_items
            )
            print(f"Logged {len(self._opik_experiment_items)} items to OPIK experiment: {self.opik_experiment_name}")
            self._opik_experiment_items = []  # Clear after successful log
        except Exception as e:
            print(f"Warning: Failed to log items to OPIK: {e}")
    
    def log_aggregate_metrics(self, metrics: Dict[str, Any]) -> None:
        """Log aggregate metrics to Comet ML and flush OPIK items.
        
        Args:
            metrics: Aggregate metrics dictionary
        """
        # Flush OPIK items before logging aggregate metrics
        if self.enabled and self.opik_client:
            self._flush_opik_items()
        
        # Log to Comet ML
        if not self.enabled or not self.experiment:
            return
        
        try:
            # Log aggregate metrics with a special step (e.g., -1) to distinguish from individual results
            aggregate_step = -1
            
            # Log aggregate metrics v2 with consistent naming
            # Retrieval metrics
            if "avg_recall_at_5" in metrics:
                self.experiment.log_metric("avg_recall_at_5", metrics["avg_recall_at_5"], step=aggregate_step)
            if "avg_recall_at_10" in metrics:
                self.experiment.log_metric("avg_recall_at_10", metrics["avg_recall_at_10"], step=aggregate_step)
            if "avg_mrr" in metrics:
                self.experiment.log_metric("avg_mrr", metrics["avg_mrr"], step=aggregate_step)
            if "avg_hit_at_1" in metrics:
                self.experiment.log_metric("avg_hit_at_1", metrics["avg_hit_at_1"], step=aggregate_step)
            
            # Evaluation metrics
            if "avg_id_normalization_success_rate" in metrics:
                self.experiment.log_metric("avg_id_normalization_success_rate", metrics["avg_id_normalization_success_rate"], step=aggregate_step)
            if "avg_multi_source_coverage" in metrics:
                self.experiment.log_metric("avg_multi_source_coverage", metrics["avg_multi_source_coverage"], step=aggregate_step)
            
            # Generation metrics
            if "avg_answer_completeness" in metrics:
                self.experiment.log_metric("avg_answer_completeness", metrics["avg_answer_completeness"], step=aggregate_step)
            if "avg_evidence_binding_rate" in metrics:
                self.experiment.log_metric("avg_evidence_binding_rate", metrics["avg_evidence_binding_rate"], step=aggregate_step)
            if "avg_over_summarization_rate" in metrics:
                self.experiment.log_metric("avg_over_summarization_rate", metrics["avg_over_summarization_rate"], step=aggregate_step)
            # Phase 2 generation KPIs (run_simple_eval aggregate_metrics)
            if "template_only_rate" in metrics:
                self.experiment.log_metric("template_only_rate", metrics["template_only_rate"], step=aggregate_step)
            if "intent_alignment_rate" in metrics:
                self.experiment.log_metric("intent_alignment_rate", metrics["intent_alignment_rate"], step=aggregate_step)
            if "completeness_gate_pass" in metrics:
                self.experiment.log_metric(
                    "completeness_gate_pass", float(metrics["completeness_gate_pass"]), step=aggregate_step
                )
            if "miss_rate_gate_pass" in metrics:
                self.experiment.log_metric(
                    "miss_rate_gate_pass", float(metrics["miss_rate_gate_pass"]), step=aggregate_step
                )
            if "generation_kpis_pass" in metrics:
                self.experiment.log_metric(
                    "generation_kpis_pass", float(metrics["generation_kpis_pass"]), step=aggregate_step
                )
            
            # Safety metrics v2
            if "avg_relevance" in metrics:
                self.experiment.log_metric("avg_relevance", metrics["avg_relevance"], step=aggregate_step)
            if "avg_hallucination_fact_error" in metrics:
                self.experiment.log_metric("avg_hallucination_fact_error", metrics["avg_hallucination_fact_error"], step=aggregate_step)
            if "avg_hallucination_unsourced_claim" in metrics:
                self.experiment.log_metric("avg_hallucination_unsourced_claim", metrics["avg_hallucination_unsourced_claim"], step=aggregate_step)
            if "avg_hallucination_overreach" in metrics:
                self.experiment.log_metric("avg_hallucination_overreach", metrics["avg_hallucination_overreach"], step=aggregate_step)
            if "fact_error_rate" in metrics:
                self.experiment.log_metric("fact_error_rate", metrics["fact_error_rate"], step=aggregate_step)
            if "unsupported_content_rate" in metrics:
                self.experiment.log_metric("unsupported_content_rate", metrics["unsupported_content_rate"], step=aggregate_step)
            # Legacy compatibility
            if "avg_hallucination" in metrics:
                self.experiment.log_metric("avg_hallucination_deprecated", metrics["avg_hallucination"], step=aggregate_step)
            
            if "pii_leakage_rate" in metrics:
                self.experiment.log_metric("pii_leakage_rate", metrics["pii_leakage_rate"], step=aggregate_step)
            if "prohibited_mention_rate" in metrics:
                self.experiment.log_metric("prohibited_mention_rate", metrics["prohibited_mention_rate"], step=aggregate_step)
            if "prohibited_mention_rate.confirmation" in metrics:
                self.experiment.log_metric("prohibited_mention_rate.confirmation", metrics["prohibited_mention_rate.confirmation"], step=aggregate_step)
            if "prohibited_mention_rate.enumeration" in metrics:
                self.experiment.log_metric("prohibited_mention_rate.enumeration", metrics["prohibited_mention_rate.enumeration"], step=aggregate_step)
            
            if "success_rate" in metrics:
                self.experiment.log_metric("success_rate", metrics["success_rate"], step=aggregate_step)
            
            if "avg_recall_at_5_strict" in metrics:
                self.experiment.log_metric(
                    "avg_recall_at_5_strict", metrics["avg_recall_at_5_strict"], step=aggregate_step
                )
            if "match_tier_strict_hit_rate" in metrics:
                self.experiment.log_metric(
                    "match_tier_strict_hit_rate", metrics["match_tier_strict_hit_rate"], step=aggregate_step
                )
            if "match_tier_normalized_only_rate" in metrics:
                self.experiment.log_metric(
                    "match_tier_normalized_only_rate",
                    metrics["match_tier_normalized_only_rate"],
                    step=aggregate_step,
                )
            if "match_tier_miss_rate" in metrics:
                self.experiment.log_metric(
                    "match_tier_miss_rate", metrics["match_tier_miss_rate"], step=aggregate_step
                )
            if "pii_true_leak_suspected_rate" in metrics:
                self.experiment.log_metric(
                    "pii_true_leak_suspected_rate", metrics["pii_true_leak_suspected_rate"], step=aggregate_step
                )
            if "pii_policy_allowed_contact_rate" in metrics:
                self.experiment.log_metric(
                    "pii_policy_allowed_contact_rate",
                    metrics["pii_policy_allowed_contact_rate"],
                    step=aggregate_step,
                )
            if "pii_false_positive_prone_rate" in metrics:
                self.experiment.log_metric(
                    "pii_false_positive_prone_rate", metrics["pii_false_positive_prone_rate"], step=aggregate_step
                )
            if "rag_health_score" in metrics:
                self.experiment.log_metric("rag_health_score", metrics["rag_health_score"], step=aggregate_step)
            if "rag_health_pass" in metrics:
                self.experiment.log_metric("rag_health_pass", metrics["rag_health_pass"], step=aggregate_step)
            if "semantic_neighbor_hit_rate" in metrics:
                self.experiment.log_metric(
                    "semantic_neighbor_hit_rate", metrics["semantic_neighbor_hit_rate"], step=aggregate_step
                )
            if "match_tier_semantic_rate" in metrics:
                self.experiment.log_metric(
                    "match_tier_semantic_rate", metrics["match_tier_semantic_rate"], step=aggregate_step
                )
            
            # Question type breakdown
            if "by_question_type" in metrics:
                for q_type, type_metrics in metrics["by_question_type"].items():
                    for metric_name, metric_value in type_metrics.items():
                        if isinstance(metric_value, (int, float)):
                            self.experiment.log_metric(f"{metric_name}.{q_type}", metric_value, step=aggregate_step)
            
            # Log summary as text
            kpi_line = (
                "KPI: normalized recall up vs baseline AND fact_error_rate=0 (gates: "
                "avg_recall_at_5>0.4, fact_error_rate==0, match_tier_miss_rate<0.5 when present)."
            )
            health_line = metrics.get("rag_health_summary", "N/A")
            if "rag_health_score" in metrics:
                health_line = (
                    f"{health_line} | rag_health_score={metrics.get('rag_health_score', 0.0):.4f} "
                    f"pass={metrics.get('rag_health_pass', 0.0):.0f}"
                )
            strict_line = ""
            if "avg_recall_at_5_strict" in metrics:
                strict_line = f"Avg Recall@5 (strict): {metrics.get('avg_recall_at_5_strict', 0.0):.4f}\n"
            mt_line = ""
            if "match_tier_strict_hit_rate" in metrics:
                mt_line = (
                    f"match_tier strict/normalized/miss: "
                    f"{metrics.get('match_tier_strict_hit_rate', 0.0):.2%} / "
                    f"{metrics.get('match_tier_normalized_only_rate', 0.0):.2%} / "
                    f"{metrics.get('match_tier_miss_rate', 0.0):.2%}\n"
                )
            pii_line = (
                f"PII leak_suspected / policy_allowed / fp_prone: "
                f"{metrics.get('pii_true_leak_suspected_rate', 0.0):.2%} / "
                f"{metrics.get('pii_policy_allowed_contact_rate', 0.0):.2%} / "
                f"{metrics.get('pii_false_positive_prone_rate', 0.0):.2%}\n"
            )
            summary_text = (
                f"{kpi_line}\n"
                f"Health: {health_line}\n"
                f"---\n"
                f"Aggregate Metrics Summary:\n"
                f"Total questions: {metrics.get('total_questions', 0)}\n"
                f"Successful questions: {metrics.get('successful_questions', 0)}\n"
                f"Success rate: {metrics.get('success_rate', 0.0):.2%}\n"
                f"Avg Recall@5 (normalized): {metrics.get('avg_recall_at_5', 0.0):.4f}\n"
                f"{strict_line}"
                f"Avg Recall@10: {metrics.get('avg_recall_at_10', 0.0):.4f}\n"
                f"Avg MRR: {metrics.get('avg_mrr', 0.0):.4f}\n"
                f"{mt_line}"
                f"Avg Relevance: {metrics.get('avg_relevance', 0.0):.4f}\n"
                f"Fact error rate: {metrics.get('fact_error_rate', metrics.get('avg_hallucination_fact_error', 0.0)):.4f}\n"
                f"Avg Hallucination (legacy): {metrics.get('avg_hallucination', 0.0):.4f}\n"
                f"{pii_line}"
                f"PII Leakage Rate: {metrics.get('pii_leakage_rate', 0.0):.2%}\n"
                f"Prohibited Mention Rate: {metrics.get('prohibited_mention_rate', 0.0):.2%}"
            )
            self.experiment.log_text(summary_text, step=aggregate_step, metadata={"type": "aggregate_summary"})
            
            # Also log as parameters for easy filtering
            self.experiment.log_parameters({
                "total_questions": metrics.get("total_questions", 0),
                "successful_questions": metrics.get("successful_questions", 0),
            })
            try:
                hp = float(metrics.get("rag_health_pass", 0.0) or 0.0)
                self.experiment.add_tags([f"rag_health:{'pass' if hp >= 0.5 else 'fail'}"])
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: Failed to log aggregate metrics to Comet: {e}")
    
    def close(self) -> None:
        """Close Comet ML experiment and OPIK client."""
        # Flush queued experiment rows (chat sessions never call log_aggregate_metrics)
        if self.enabled and self.opik_client:
            self._flush_opik_items()

        # Close Comet ML experiment
        if self.enabled and self.experiment:
            try:
                self.experiment.end()
            except Exception as e:
                print(f"Warning: Failed to close Comet experiment: {e}")
        
        # Close OPIK client
        if self.enabled and self.opik_client:
            try:
                self.opik_client.end()
            except Exception as e:
                print(f"Warning: Failed to close OPIK client: {e}")
