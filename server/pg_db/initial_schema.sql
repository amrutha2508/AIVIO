CREATE TABLE interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,

    hcp_name TEXT,
    interaction_type TEXT,
    interaction_date DATE,
    interaction_time TIME,
    attendees TEXT[],

    materials_shared TEXT[],
    samples_distributed TEXT[],

    hcp_sentiment TEXT CHECK (
        hcp_sentiment IN ('positive', 'neutral', 'negative')
    ),

    outcomes TEXT,
    follow_up_actions TEXT[],

    status TEXT DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE interaction_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interaction_id UUID REFERENCES interactions(id) ON DELETE CASCADE,
    role TEXT CHECK (role IN ('user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE interaction_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interaction_id UUID REFERENCES interactions(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    previous_data JSONB,
    new_data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);