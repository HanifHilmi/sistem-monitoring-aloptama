/** Links inside the app. Each system has its own board and sites, so a second system (AWOS CAT. I) fits in. */
export const boardPath = (code: string) => `/systems/${encodeURIComponent(code)}`
export const sitePath = (code: string, slug: string) => `${boardPath(code)}/sites/${encodeURIComponent(slug)}`
