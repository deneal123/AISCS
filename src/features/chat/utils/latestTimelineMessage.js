/** Reloaded history and retained live messages may overlap, but time still owns the latest result. */
export function latestTimelineMessage(messages, accepts = () => true) {
  let latest = null;
  for (const message of messages) {
    if (!accepts(message)) continue;
    if (latest && Date.parse(message.timestamp) < Date.parse(latest.timestamp)) continue;
    latest = message;
  }
  return latest;
}

export function latestReplyAfterAnchor(messages, anchor) {
  if (!anchor) return null;
  const start = messages.indexOf(anchor);
  const requestedAt = Date.parse(anchor.timestamp);
  return latestTimelineMessage(messages.filter((message, index) => {
    if (!['agent', 'assistant'].includes(message.type)) return false;
    const repliedAt = Date.parse(message.timestamp);
    if (Number.isFinite(requestedAt) && Number.isFinite(repliedAt)) {
      return repliedAt > requestedAt || (repliedAt === requestedAt && index > start);
    }
    return index > start;
  }));
}
