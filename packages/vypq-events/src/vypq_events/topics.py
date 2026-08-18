from vypq_contracts.common import Task

CRAWL_DOCUMENTS_READY = "crawl.documents.ready"


def request_topic(task: Task) -> str:
    return f"infer.{task.value}.requests"


def result_topic(task: Task) -> str:
    return f"infer.{task.value}.results"


def dlq_topic(task: Task) -> str:
    return f"infer.{task.value}.dlq"
