CREATE TABLE registration_schema_version (version INT PRIMARY KEY);
INSERT INTO registration_schema_version VALUES (1);
REVOKE ALL ON registration_schema_version FROM PUBLIC;
ALTER TABLE registration_schema_version ENABLE ROW LEVEL SECURITY;
