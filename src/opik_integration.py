"""OPIK integration for Comet logging (optional).

This module provides optional integration with Comet/OPIK for logging
evaluation results. It is only used when ENABLE_COMET_LOGGING=true.
"""

from typing import Dict, List, Any, Optional
from src.config import Config


class OpikIntegration:
    """OPIK integration for Comet logging."""
    
    def __init__(self, config: Config):
        """Initialize OPIK integration.
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.enabled = config.enable_comet_logging
        
        if not self.enabled:
            return
        
        # Only import comet/opik if enabled
        try:
            from comet_ml import Experiment
            self.Experiment = Experiment
        except ImportError:
            print("Warning: comet-ml not installed. Comet logging will be disabled.")
            self.enabled = False
            return
        
        # Initialize Comet experiment if API key is provided
        if config.comet_api_key:
            try:
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
                self.enabled = False
                self.experiment = None
        else:
            print("Warning: COMET_API_KEY not set. Comet logging will be disabled.")
            self.enabled = False
            self.experiment = None
    
    def log_evaluation_result(self, result: Dict[str, Any]) -> None:
        """Log a single evaluation result to Comet.
        
        Args:
            result: Evaluation result dictionary
        """
        if not self.enabled or not self.experiment:
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
                # Core retrieval metrics
                self.experiment.log_metric("recall_at_5", result.get("recall_at_5", 0.0), step=step)
                self.experiment.log_metric("recall_at_10", result.get("recall_at_10", 0.0), step=step)
                self.experiment.log_metric("mrr", result.get("mrr", 0.0), step=step)
                
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
            print(f"Warning: Failed to log result to Comet: {e}")
    
    def log_aggregate_metrics(self, metrics: Dict[str, Any]) -> None:
        """Log aggregate metrics to Comet.
        
        Args:
            metrics: Aggregate metrics dictionary
        """
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
        """Close Comet experiment."""
        if self.enabled and self.experiment:
            try:
                self.experiment.end()
            except Exception as e:
                print(f"Warning: Failed to close Comet experiment: {e}")
