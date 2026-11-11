import { z } from "zod";
import { text } from "../../lib/validation";

export const applicationSchema = z.object({
  cover_note: text(0, 1000).nullish(),
});
