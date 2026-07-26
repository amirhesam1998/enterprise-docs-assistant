export type Level = "creator" | "admin" | "user";

export interface RoleBrief {
  id: number;
  name: string;
}

export interface Me {
  username: string;
  level: Level;
  tenant_id: string;
  acl_groups: string[];
  roles: RoleBrief[];
  permissions: string[];
}

export interface Permission {
  id: number;
  name: string;
  description: string;
}

export interface Role {
  id: number;
  name: string;
  description: string;
  permissions: Permission[];
}

export interface AdminUser {
  id: number;
  username: string;
  email: string | null;
  level: Level;
  tenant_id: string;
  acl_groups: string[];
  roles: RoleBrief[];
  permissions: string[]; // effective (union across roles)
}

/** location is polymorphic across source kinds. */
export type SourceLocation =
  | { type: "cell"; sheet: string; row: number; ref?: string | null }
  | { type: "page"; num: number }
  | { type: string; [k: string]: unknown };

export interface Source {
  ref: string | null;
  source: string;
  location: SourceLocation;
  score: number;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
}

/** POST /documents/upload — accepted, not finished. The work happens in a worker. */
export interface UploadAccepted {
  job_id: string;
  status: string; // "queued"
  source: string;
}

/** What a finished ingestion actually put into the index. */
export interface IngestResult {
  chunks: number;
  source: string;
  tenant_id: string;
}

/** Celery states, plus our own optimistic "queued" before the first poll lands. */
export type JobPhase =
  | "queued"
  | "PENDING"
  | "STARTED"
  | "RETRY"
  | "SUCCESS"
  | "FAILURE"
  | (string & {});

export interface JobStatus {
  job_id: string;
  status: JobPhase;
  result: IngestResult | null;
  error: string | null;
}
