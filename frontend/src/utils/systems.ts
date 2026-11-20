import type { Locale } from '@/i18n'
import type { SystemInfo } from '@/api/types'

/** Systems SIMOLA will monitor later (names under `nav.upcoming`): listed greyed out, with a "coming soon" note. */
export const UPCOMING_SYSTEMS = [
  { code: 'soon-cat1', key: 'cat1' },
  { code: 'soon-aws-digi', key: 'awsDigi' },
  { code: 'soon-aws-arg', key: 'awsArg' },
] as const

/** "AWOS CAT. III WIDN" -> "AWOS CAT. III": the airport is the same for every system. */
export const shortName = (s: SystemInfo, lc: Locale): string =>
  s.name[lc].replace(new RegExp(`\\s*${s.icao ?? '$^'}\\s*$`), '')
