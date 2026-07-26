import type { Level } from "../api/types";

/**
 * The seeded demo accounts from API.md. These power the one-click login
 * shortcuts AND the identity-comparison feature (which logs in as another demo
 * user behind the scenes to re-run a question). Credentials are intentionally
 * public here — this is a portfolio demo, not a production secret store.
 */
export interface DemoAccount {
  username: string;
  password: string;
  level: Level;
  tenant: string;
  groups: string[];
  blurb: string;
}

export const DEMO_ACCOUNTS: DemoAccount[] = [
  {
    username: "creator",
    password: "creator123",
    level: "creator",
    tenant: "kb",
    groups: [],
    blurb: "Full clearance. Bypasses every check.",
  },
  {
    username: "sara",
    password: "sara123",
    level: "admin",
    tenant: "kb",
    groups: ["billing"],
    blurb: "Admin · manages users · reads billing docs.",
  },
  {
    username: "reza",
    password: "reza123",
    level: "admin",
    tenant: "kb",
    groups: ["security"],
    blurb: "Admin · read-only panel · reads security docs.",
  },
  {
    username: "ali",
    password: "ali123",
    level: "user",
    tenant: "postgres",
    groups: ["engineering"],
    blurb: "User · engineering docs only.",
  },
  {
    username: "maryam",
    password: "maryam123",
    level: "user",
    tenant: "postgres",
    groups: ["hr"],
    blurb: "User · HR docs only.",
  },
  {
    username: "dana",
    password: "dana123",
    level: "user",
    tenant: "acme-internal",
    groups: ["sales"],
    blurb: "User · sales docs, different tenant.",
  },
];
