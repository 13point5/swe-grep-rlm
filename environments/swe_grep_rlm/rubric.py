import verifiers as vf

from rewards import (
    exact_match,
    gold_file_count,
    predicted_file_count,
    retrieval_f1,
    retrieval_precision,
    retrieval_recall,
)


def build_rubric() -> vf.Rubric:
    rubric = vf.Rubric(funcs=[retrieval_f1])
    rubric.add_metric(retrieval_precision)
    rubric.add_metric(retrieval_recall)
    rubric.add_metric(exact_match)
    rubric.add_metric(predicted_file_count)
    rubric.add_metric(gold_file_count)
    return rubric
