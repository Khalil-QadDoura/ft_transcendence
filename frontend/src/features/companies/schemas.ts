import { z } from "zod";
import { text } from "../../lib/validation";

// BE-21's supported subset, not a claim to include every ISO country.
const countries = new Set(
  "AZ TR ID RU US GB DE FR AE SA KZ UA UZ GE AM BY TM KG TJ MD PL CZ RO HU RS HR BA ME MK AL CN JP KR IN PK BD PH VN TH MY BR AR MX CO PE CL VE EC BO PY EG MA NG ZA KE ET TZ GH SN CI".split(
    " ",
  ),
);
const countryCode = text(2, 2)
  .toUpperCase()
  .refine((code) => countries.has(code), { message: "validation.country" });
export const companyCreateSchema = z.object({
  name: text(1, 150),
  description: text().nullish(),
  country: text(0, 100).nullish(),
  city: text(0, 100).nullish(),
  district: text(0, 100).nullish(),
});
export const companyUpdateSchema = z.strictObject({
  name: text(1, 150),
  country: text(1, 100),
  city: text(1, 100),
  district: text(0, 100).nullish(),
  country_code: countryCode.nullish(),
});
