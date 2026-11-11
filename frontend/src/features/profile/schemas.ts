import { z } from "zod";
import { adultBirthDate, text } from "../../lib/validation";

export const createProfileSchema = (today = new Date()) =>
  z.strictObject({
    first_name: text(1, 50, true),
    last_name: text(1, 50, true),
    position: text(1, 100, true),
    birth_date: adultBirthDate(today),
    bio: text(0, 500, true).nullish(),
  });
// Full onboarding versus BE-05's partial PATCH; omitted fields must remain omitted.
export const createProfilePatchSchema = (today = new Date()) =>
  createProfileSchema(today).partial();
