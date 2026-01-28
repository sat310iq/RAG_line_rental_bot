"""OPIK integration for Comet logging (optional).

This module provides optional integration with Comet/OPIK for logging
evaluation results. It is only used when ENABLE_COMET_LOGGING=true.

Supports both Comet ML (comet_ml.Experiment) and OPIK SDK (opik.Opik) for logging.
"""

from typing import Dict, List, Any, Optional
from src.config import Config


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
                # Core retrieval metrics (only if not None)
                recall_at_5 = result.get("recall_at_5")
                if recall_at_5 is not None:
                    self.experiment.log_metric("recall_at_5", recall_at_5, step=step)
                recall_at_10 = result.get("recall_at_10")
                if recall_at_10 is not None:
                    self.experiment.log_metric("recall_at_10", recall_at_10, step=step)
                mrr = result.get("mrr")
                if mrr is not None:
                    self.experiment.log_metric("mrr", mrr, step=step)
                
                # LLM evaluation metrics
                self.experiment.log_metric("relevance", result.get("relevance", 0.0), step=step)
                self.experiment.log_metric("hallucination", result.get("hallucination", 0.0), step=step)
                
                # Rule-based metrics (as binary 0/1)
                self.experiment.log_metric("contains_pii", 1.0 if result.get("contains_pii", False) else 0.0, step=step)
                self.experiment.log_metric("mentions_prohibited", 1.0 if result.get("mentions_prohibited", False) else 0.0, step=step)
                
                # Log question details as text with metadata
                self.experiment.log_text(
                    f"Question: {result.get('question', '')}\n"
                    f"Answer: {result.get('answer_text', '')}\n"
                    f"Retrieved IDs: {result.get('retrieved_ids', [])}\n"
                    f"Expected IDs: {result.get('expected_doc_ids', [])}",
                    step=step,
                    metadata={
                        "question_id": question_id,
                        "category": result.get("category", ""),
                        "success": True
                    }
                )
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
                
                # Create feedback scores from metrics (skip None values)
                feedback_scores = []
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
                if "relevance" in result and result.get("relevance") is not None:
                    feedback_scores.append({
                        "name": "relevance",
                        "value": result.get("relevance", 0.0),
                        "source": "sdk"
                    })
                if "hallucination" in result and result.get("hallucination") is not None:
                    feedback_scores.append({
                        "name": "hallucination",
                        "value": result.get("hallucination", 0.0),
                        "source": "sdk"
                    })
                if "mrr" in result and result.get("mrr") is not None:
                    feedback_scores.append({
                        "name": "mrr",
                        "value": result.get("mrr", 0.0),
                        "source": "sdk"
                    })
                
                # Add to batch for bulk logging (using UUID)
                experiment_item = {
                    "dataset_item_id": dataset_item_id,
                    "evaluate_task_result": {
                        "prediction": result.get("answer_text", ""),
                    },
                    "feedback_scores": feedback_scores,
                }
                
                # Add thread_id to metadata if present (for chat sessions)
                thread_id = result.get("thread_id")
                if thread_id:
                    experiment_item["metadata"] = {"thread_id": thread_id}
                
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
            
            # Log aggregate metrics with consistent naming
            if "avg_recall_at_5" in metrics:
                self.experiment.log_metric("avg_recall_at_5", metrics["avg_recall_at_5"], step=aggregate_step)
            if "avg_recall_at_10" in metrics:
                self.experiment.log_metric("avg_recall_at_10", metrics["avg_recall_at_10"], step=aggregate_step)
            if "avg_mrr" in metrics:
                self.experiment.log_metric("avg_mrr", metrics["avg_mrr"], step=aggregate_step)
            if "avg_relevance" in metrics:
                self.experiment.log_metric("avg_relevance", metrics["avg_relevance"], step=aggregate_step)
            if "avg_hallucination" in metrics:
                self.experiment.log_metric("avg_hallucination", metrics["avg_hallucination"], step=aggregate_step)
            if "pii_leakage_rate" in metrics:
                self.experiment.log_metric("pii_leakage_rate", metrics["pii_leakage_rate"], step=aggregate_step)
            if "prohibited_mention_rate" in metrics:
                self.experiment.log_metric("prohibited_mention_rate", metrics["prohibited_mention_rate"], step=aggregate_step)
            if "success_rate" in metrics:
                self.experiment.log_metric("success_rate", metrics["success_rate"], step=aggregate_step)
            
            # Log summary as text
            summary_text = (
                f"Aggregate Metrics Summary:\n"
                f"Total questions: {metrics.get('total_questions', 0)}\n"
                f"Successful questions: {metrics.get('successful_questions', 0)}\n"
                f"Success rate: {metrics.get('success_rate', 0.0):.2%}\n"
                f"Avg Recall@5: {metrics.get('avg_recall_at_5', 0.0):.4f}\n"
                f"Avg Recall@10: {metrics.get('avg_recall_at_10', 0.0):.4f}\n"
                f"Avg MRR: {metrics.get('avg_mrr', 0.0):.4f}\n"
                f"Avg Relevance: {metrics.get('avg_relevance', 0.0):.4f}\n"
                f"Avg Hallucination: {metrics.get('avg_hallucination', 0.0):.4f}\n"
                f"PII Leakage Rate: {metrics.get('pii_leakage_rate', 0.0):.2%}\n"
                f"Prohibited Mention Rate: {metrics.get('prohibited_mention_rate', 0.0):.2%}"
            )
            self.experiment.log_text(summary_text, step=aggregate_step, metadata={"type": "aggregate_summary"})
            
            # Also log as parameters for easy filtering
            self.experiment.log_parameters({
                "total_questions": metrics.get("total_questions", 0),
                "successful_questions": metrics.get("successful_questions", 0),
            })
        except Exception as e:
            print(f"Warning: Failed to log aggregate metrics to Comet: {e}")
    
    def close(self) -> None:
        """Close Comet ML experiment and OPIK client."""
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
