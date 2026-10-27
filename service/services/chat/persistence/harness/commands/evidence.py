"""Keep current criterion facts bounded; immutable history stays in operation receipts."""


def latest_evidence(previous, additional):
    latest = {item.criterion_id: item for item in previous}
    latest.update({item.criterion_id: item for item in additional})
    return list(latest.values())
