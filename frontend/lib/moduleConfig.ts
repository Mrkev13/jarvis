/**
 * Jediné místo frontendu, které čte flagy modulů z prostředí (Roadmap 6C).
 *
 * Next.js vkládá `NEXT_PUBLIC_*` do klientského bundlu při `next build` – proto každý flag doslovně
 * (dynamický přístup `process.env[name]` by se nevložil). Do prohlížeče se tak dostanou jen tyto
 * booleovské přepínače, nic jiného. Změna flagu = nový build (stejně jako NEXT_PUBLIC_API_URL).
 * Backend má vlastní `MODULE_<ID>_ENABLED` v backend/.env (data, API, AI) – nastav oba stejně.
 */
import { createModuleAccess, resolveModuleFlags, type ModuleAccess } from "./modules.ts";

export const MODULE_FLAGS = resolveModuleFlags({
  NEXT_PUBLIC_MODULE_SCHOOL_ENABLED: process.env.NEXT_PUBLIC_MODULE_SCHOOL_ENABLED,
  NEXT_PUBLIC_MODULE_WORK_ENABLED: process.env.NEXT_PUBLIC_MODULE_WORK_ENABLED,
  NEXT_PUBLIC_MODULE_FINANCE_ENABLED: process.env.NEXT_PUBLIC_MODULE_FINANCE_ENABLED,
  NEXT_PUBLIC_MODULE_GOALS_ENABLED: process.env.NEXT_PUBLIC_MODULE_GOALS_ENABLED,
  NEXT_PUBLIC_MODULE_WOT_ENABLED: process.env.NEXT_PUBLIC_MODULE_WOT_ENABLED,
  NEXT_PUBLIC_MODULE_MFF_ENABLED: process.env.NEXT_PUBLIC_MODULE_MFF_ENABLED,
  NEXT_PUBLIC_MODULE_FOOD_ENABLED: process.env.NEXT_PUBLIC_MODULE_FOOD_ENABLED,
  NEXT_PUBLIC_MODULE_FITNESS_ENABLED: process.env.NEXT_PUBLIC_MODULE_FITNESS_ENABLED,
  NEXT_PUBLIC_MODULE_HABITS_ENABLED: process.env.NEXT_PUBLIC_MODULE_HABITS_ENABLED,
  NEXT_PUBLIC_MODULE_PROJECTS_ENABLED: process.env.NEXT_PUBLIC_MODULE_PROJECTS_ENABLED,
  NEXT_PUBLIC_MODULE_KNOWLEDGE_ENABLED: process.env.NEXT_PUBLIC_MODULE_KNOWLEDGE_ENABLED,
  NEXT_PUBLIC_MODULE_CAR_ENABLED: process.env.NEXT_PUBLIC_MODULE_CAR_ENABLED,
  NEXT_PUBLIC_MODULE_TRAVEL_ENABLED: process.env.NEXT_PUBLIC_MODULE_TRAVEL_ENABLED,
  NEXT_PUBLIC_MODULE_ENTERTAINMENT_ENABLED: process.env.NEXT_PUBLIC_MODULE_ENTERTAINMENT_ENABLED,
});

export const MODULE_ACCESS: ModuleAccess = createModuleAccess(MODULE_FLAGS);
