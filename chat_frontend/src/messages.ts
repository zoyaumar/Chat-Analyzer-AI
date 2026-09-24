import type { Message } from "./types";

function compareMessages(left: Message, right: Message): number {
  const timestampOrder = String(left.timestamp ?? "").localeCompare(
    String(right.timestamp ?? "")
  );
  return timestampOrder || left.id - right.id;
}

export function mergeMessages(
  current: Message[],
  incoming: Message[]
): Message[] {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) {
    byId.set(message.id, message);
  }
  return [...byId.values()].sort(compareMessages);
}
