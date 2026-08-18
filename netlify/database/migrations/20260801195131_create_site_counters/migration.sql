CREATE TABLE "site_counters" (
	"key" text PRIMARY KEY,
	"value" integer DEFAULT 0 NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
