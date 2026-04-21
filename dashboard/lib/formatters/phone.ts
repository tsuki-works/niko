import { parsePhoneNumberFromString } from 'libphonenumber-js';

export function formatPhone(raw: string | null | undefined): string {
  if (!raw) return '';
  const parsed = parsePhoneNumberFromString(raw, 'CA');
  return parsed ? parsed.formatInternational() : raw;
}
