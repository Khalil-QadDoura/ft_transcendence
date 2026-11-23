import az from "./az-format.json";

// Chromium builds can lack Azerbaijani date/relative-time data even when Node
// has it. Use a deterministic catalog for names, retaining Intl time-zone math.
export function calendarDate(
  value: Date,
  language: string,
  options?: Intl.DateTimeFormatOptions,
) {
  if (language !== "az")
    return new Intl.DateTimeFormat(language, options).format(value);
  const parts = new Intl.DateTimeFormat("en-GB", options).formatToParts(value);
  const month =
    Number(
      new Intl.DateTimeFormat("en-GB", {
        month: "numeric",
        timeZone: options?.timeZone,
      }).format(value),
    ) - 1;
  const weekdays = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ];
  const weekday = weekdays.indexOf(
    new Intl.DateTimeFormat("en-GB", {
      weekday: "long",
      timeZone: options?.timeZone,
    }).format(value),
  );
  return parts
    .map((part) => {
      if (part.type === "month" && /[a-z]/i.test(part.value)) {
        return options?.month === "short" || options?.dateStyle === "medium"
          ? az.shortMonths[month]
          : az.months[month];
      }
      if (part.type === "weekday")
        return options?.weekday === "short"
          ? az.shortWeekdays[weekday]
          : az.weekdays[weekday];
      return part.type === "literal"
        ? part.value.replaceAll("/", ".")
        : part.value;
    })
    .join("");
}

export function relativePast(
  count: number,
  unit: "minute" | "hour",
  language: string,
) {
  if (language === "az")
    return az[unit === "minute" ? "minutePast" : "hourPast"].replace(
      "{{count}}",
      new Intl.NumberFormat("az").format(count),
    );
  return new Intl.RelativeTimeFormat(language, { style: "short" }).format(
    -count,
    unit,
  );
}
