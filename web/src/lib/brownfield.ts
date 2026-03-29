import type { BrownfieldRepoPlanItem, OverviewOnboarding } from "../types";

export function brownfieldRepoPlanItems(onboarding?: OverviewOnboarding | null): BrownfieldRepoPlanItem[] {
  return onboarding?.repo_plan_state?.items ?? onboarding?.repo_plan_preview?.items ?? [];
}

export function brownfieldRepoPlanTrust(onboarding?: OverviewOnboarding | null) {
  return onboarding?.repo_plan_state?.trust ?? onboarding?.repo_plan_trust ?? null;
}
