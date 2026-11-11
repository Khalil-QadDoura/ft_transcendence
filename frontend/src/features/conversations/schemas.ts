import { z } from "zod";
import { text } from "../../lib/validation";

export const messageSchema = z.object({
  content: text(1, 4000),
  idempotency_key: text(0, 64).nullish(),
});
