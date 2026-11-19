// Sharma Electronics (PAYTM_MERCH_8821) is the only merchant. Its data comes from the team seed in /data/seed.
import { buildSharma } from './seedSharma.js'

const sharma = buildSharma()
export const MERCHANTS = { [sharma.slug]: sharma }
export const MERCHANT_LIST = [{ slug: sharma.slug, name: sharma.profile.name, type: sharma.profile.category }]
export const DEFAULT_MERCHANT = sharma.slug
