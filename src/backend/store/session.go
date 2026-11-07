package store

import (
	"crypto/rand"
	"fmt"
	"sync"
	"time"

	"chat-app/backend/model"
)

const sessionTTL = 30 * time.Minute

type sessionEntry struct {
	session   model.Session
	expiresAt time.Time
	mu        sync.Mutex
}

type SessionStore struct {
	mu       sync.RWMutex
	sessions map[string]*sessionEntry
	ttl      time.Duration
}

func NewSessionStore() *SessionStore {
	return &SessionStore{
		sessions: make(map[string]*sessionEntry),
		ttl:      sessionTTL,
	}
}

func (s *SessionStore) Create() (*model.Session, error) {
	s.CleanupExpired()

	for {
		id, err := newSessionID()
		if err != nil {
			return nil, err
		}

		s.mu.Lock()
		if _, exists := s.sessions[id]; exists {
			s.mu.Unlock()
			continue
		}
		entry := &sessionEntry{
			session:   model.Session{ID: id},
			expiresAt: time.Now().Add(s.ttl),
		}
		s.sessions[id] = entry
		s.mu.Unlock()

		session := entry.session
		return &session, nil
	}
}

func (s *SessionStore) Get(id string) (*model.Session, bool) {
	session, unlock, ok := s.Lock(id)
	if !ok {
		return nil, false
	}
	defer unlock()

	copy := *session
	copy.History = append([]model.Message(nil), session.History...)
	return &copy, true
}

func (s *SessionStore) Update(id string, updated *model.Session) bool {
	if updated == nil {
		return false
	}

	session, unlock, ok := s.Lock(id)
	if !ok {
		return false
	}
	defer unlock()

	session.SystemPrompt = updated.SystemPrompt
	session.History = append([]model.Message(nil), updated.History...)
	return true
}

func (s *SessionStore) UpdateSystemPrompt(id, systemPrompt string) bool {
	session, unlock, ok := s.Lock(id)
	if !ok {
		return false
	}
	defer unlock()

	session.SystemPrompt = systemPrompt
	return true
}

func (s *SessionStore) ResetHistory(id string) bool {
	session, unlock, ok := s.Lock(id)
	if !ok {
		return false
	}
	defer unlock()

	session.History = []model.Message{}
	return true
}

func (s *SessionStore) Delete(id string) bool {
	s.mu.RLock()
	entry := s.sessions[id]
	s.mu.RUnlock()
	if entry == nil {
		return false
	}

	entry.mu.Lock()
	defer entry.mu.Unlock()

	s.mu.Lock()
	defer s.mu.Unlock()
	if s.sessions[id] != entry {
		return false
	}
	delete(s.sessions, id)
	return true
}

func (s *SessionStore) Lock(id string) (*model.Session, func(), bool) {
	s.mu.RLock()
	entry := s.sessions[id]
	s.mu.RUnlock()
	if entry == nil {
		return nil, nil, false
	}

	entry.mu.Lock()
	s.mu.Lock()
	if s.sessions[id] != entry {
		s.mu.Unlock()
		entry.mu.Unlock()
		return nil, nil, false
	}
	if !entry.expiresAt.After(time.Now()) {
		delete(s.sessions, id)
		s.mu.Unlock()
		entry.mu.Unlock()
		return nil, nil, false
	}
	entry.expiresAt = time.Now().Add(s.ttl)
	s.mu.Unlock()

	return &entry.session, entry.mu.Unlock, true
}

func (s *SessionStore) CleanupExpired() int {
	type storedSession struct {
		id    string
		entry *sessionEntry
	}

	s.mu.RLock()
	sessions := make([]storedSession, 0, len(s.sessions))
	for id, entry := range s.sessions {
		sessions = append(sessions, storedSession{id: id, entry: entry})
	}
	s.mu.RUnlock()

	now := time.Now()
	removed := 0
	for _, current := range sessions {
		current.entry.mu.Lock()
		s.mu.Lock()
		if s.sessions[current.id] == current.entry && !current.entry.expiresAt.After(now) {
			delete(s.sessions, current.id)
			removed++
		}
		s.mu.Unlock()
		current.entry.mu.Unlock()
	}
	return removed
}

func newSessionID() (string, error) {
	var id [16]byte
	if _, err := rand.Read(id[:]); err != nil {
		return "", fmt.Errorf("generate session ID: %w", err)
	}
	id[6] = id[6]&0x0f | 0x40
	id[8] = id[8]&0x3f | 0x80

	return fmt.Sprintf("%x-%x-%x-%x-%x", id[:4], id[4:6], id[6:8], id[8:10], id[10:]), nil
}
