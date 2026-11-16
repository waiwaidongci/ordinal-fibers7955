
CREATE TABLE audits (
	id INTEGER NOT NULL AUTO_INCREMENT,
	actor VARCHAR(160) NOT NULL,
	action VARCHAR(180) NOT NULL,
	status_code INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
)

;


CREATE TABLE grade_studies (
	id INTEGER NOT NULL AUTO_INCREMENT,
	code VARCHAR(40) NOT NULL,
	name VARCHAR(140) NOT NULL,
	protocol VARCHAR(1200) NOT NULL,
	source_file VARCHAR(140) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (code)
)

;


CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT,
	email VARCHAR(160) NOT NULL,
	name VARCHAR(80) NOT NULL,
	`role` VARCHAR(20) NOT NULL,
	password_hash VARCHAR(250) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (email)
)

;


CREATE TABLE rank_test_runs (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(140) NOT NULL,
	study_id INTEGER NOT NULL,
	alpha DOUBLE NOT NULL,
	status VARCHAR(20) NOT NULL,
	snapshot JSON NOT NULL,
	result JSON NOT NULL,
	error VARCHAR(600) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name),
	FOREIGN KEY(study_id) REFERENCES grade_studies (id)
)

;


CREATE TABLE treatments (
	id INTEGER NOT NULL AUTO_INCREMENT,
	study_id INTEGER NOT NULL,
	code VARCHAR(40) NOT NULL,
	name VARCHAR(100) NOT NULL,
	process_note VARCHAR(1000) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (study_id, code),
	FOREIGN KEY(study_id) REFERENCES grade_studies (id)
)

;


CREATE TABLE followup_notes (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(140) NOT NULL,
	run_id INTEGER NOT NULL,
	rationale VARCHAR(2000) NOT NULL,
	status VARCHAR(20) NOT NULL,
	reviewer_note VARCHAR(1000) NOT NULL,
	reviewed_by VARCHAR(140) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name),
	FOREIGN KEY(run_id) REFERENCES rank_test_runs (id)
)

;


CREATE TABLE grade_readings (
	id INTEGER NOT NULL AUTO_INCREMENT,
	study_id INTEGER NOT NULL,
	treatment_id INTEGER NOT NULL,
	specimen_code VARCHAR(60) NOT NULL,
	grade DOUBLE NOT NULL,
	source_note VARCHAR(250) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (study_id, specimen_code),
	FOREIGN KEY(study_id) REFERENCES grade_studies (id),
	FOREIGN KEY(treatment_id) REFERENCES treatments (id)
)

;

CREATE TABLE dp_budgets (
	id INTEGER NOT NULL AUTO_INCREMENT,
	study_id INTEGER NOT NULL,
	total_epsilon_micros INTEGER NOT NULL,
	spent_epsilon_micros INTEGER NOT NULL,
	preset_by VARCHAR(160) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (study_id),
	FOREIGN KEY(study_id) REFERENCES grade_studies (id)
)

;


CREATE TABLE dp_publications (
	id INTEGER NOT NULL AUTO_INCREMENT,
	study_id INTEGER NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	epsilon_micros INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	noise_seed VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	result JSON NOT NULL,
	error VARCHAR(600) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (study_id, fingerprint, epsilon_micros),
	FOREIGN KEY(study_id) REFERENCES grade_studies (id)
)

;


CREATE TABLE dp_release_names (
	id INTEGER NOT NULL AUTO_INCREMENT,
	publication_id INTEGER NOT NULL,
	name VARCHAR(140) NOT NULL,
	requested_by VARCHAR(160) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name),
	FOREIGN KEY(publication_id) REFERENCES dp_publications (id)
)

;
