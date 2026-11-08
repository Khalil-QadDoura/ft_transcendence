import { z } from "zod";

// Python/Pydantic counts Unicode code points, not JavaScript UTF-16 units.
export function text(min = 0, max = Infinity, trim = false) {
  const value = z.string({ error: "validation.text" });
  return (trim ? value.trim() : value)
    .refine((s) => [...s].length >= min, { message: "validation.tooShort" })
    .refine((s) => [...s].length <= max, { message: "validation.tooLong" });
}

export const number = () => z.number({ error: "validation.number" });
export const choice = <T extends string>(values: readonly T[]) =>
  z.enum(values, { error: "validation.choice" });

// Resolver fallback for structural/type errors; rule messages also use FE-06 keys.
export const validationOptions = { error: () => "validation.invalid" };

export function adultBirthDate(today = new Date()) {
  const year = today.getFullYear();
  const month = today.getMonth() + 1;
  const day = today.getDate();
  return z.iso.date({ error: "validation.date" }).refine(
    (value) => {
      const [birthYear, birthMonth, birthDay] = value.split("-").map(Number);
      const birthdayPassed =
        month > birthMonth || (month === birthMonth && day >= birthDay);
      return (
        birthYear >= 1 && year - birthYear - (birthdayPassed ? 0 : 1) >= 18
      );
    },
    { message: "validation.adult" },
  );
}
