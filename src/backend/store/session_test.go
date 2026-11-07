package store

import (
	"fmt"
	"sync"
	"testing"
	"time"

	"chat-app/backend/model"
)

func TestCreateGeneratesUniqueSessionIDs(t *testing.T) {
	store := NewSessionStore()
	first, err := store.Create()
	if err != nil {
		t.Fatalf("create first session: %v", err)
	}
	second, err := store.Create()
	if err != nil {
		t.Fatalf("create second session: %v", err)
	}
	if first.ID == second.ID {
		t.Fatalf("session IDs are not unique: %q", first.ID)
	}
	if len(first.ID) != 36 {
		t.Fatalf("session ID length = %d, want UUID length 36", len(first.ID))
	}
}

func TestGetSession(t *testing.T) {
	store := NewSessionStore()
	created, err := store.Create()
	if err != nil {
		t.Fatalf("create session: %v", err)
	}

	got, ok := store.Get(created.ID)
	if !ok {
		t.Fatal("Get returned false for an existing session")
	}
	if got.ID != created.ID {
		t.Fatalf("ID = %q, want %q", got.ID, created.ID)
	}
}

func TestGetMissingSession(t *testing.T) {
	if _, ok := NewSessionStore().Get("missing"); ok {
		t.Fatal("Get returned true for a missing session")
	}
}

func TestUpdateSessionHistory(t *testing.T) {
	store := NewSessionStore()
	created, err := store.Create()
	if err != nil {
		t.Fatalf("create session: %v", err)
	}
	updated := &model.Session{
		ID:           created.ID,
		SystemPrompt: "Be helpful",
		History:      []model.Message{{Role: "user", Content: "Hello"}},
	}

	if !store.Update(created.ID, updated) {
		t.Fatal("Update returned false for an existing session")
	}
	got, ok := store.Get(created.ID)
	if !ok {
		t.Fatal("updated session could not be retrieved")
	}
	if got.SystemPrompt != updated.SystemPrompt || len(got.History) != 1 ||
		got.History[0] != updated.History[0] {
		t.Fatalf("updated session = %#v, want %#v", got, updated)
	}
}

func TestDeleteSession(t *testing.T) {
	store := NewSessionStore()
	created, err := store.Create()
	if err != nil {
		t.Fatalf("create session: %v", err)
	}

	if !store.Delete(created.ID) {
		t.Fatal("Delete returned false for an existing session")
	}
	if _, ok := store.Get(created.ID); ok {
		t.Fatal("deleted session can still be retrieved")
	}
}

func TestGetSessionBeforeExpiration(t *testing.T) {
	store := NewSessionStore()
	created, err := store.Create()
	if err != nil {
		t.Fatalf("create session: %v", err)
	}

	if _, ok := store.Get(created.ID); !ok {
		t.Fatal("session expired before its TTL")
	}
}

func TestGetDeletesExpiredSession(t *testing.T) {
	store := NewSessionStore()
	created, err := store.Create()
	if err != nil {
		t.Fatalf("create session: %v", err)
	}
	store.mu.Lock()
	store.sessions[created.ID].expiresAt = time.Now().Add(-time.Second)
	store.mu.Unlock()

	if _, ok := store.Get(created.ID); ok {
		t.Fatal("Get returned true for an expired session")
	}
	store.mu.RLock()
	_, exists := store.sessions[created.ID]
	store.mu.RUnlock()
	if exists {
		t.Fatal("expired session was not removed")
	}
}

func TestConcurrentOperationsOnMultipleSessions(t *testing.T) {
	store := NewSessionStore()
	const count = 64
	var workers sync.WaitGroup
	workers.Add(count)
	for i := 0; i < count; i++ {
		go func(i int) {
			defer workers.Done()
			session, err := store.Create()
			if err != nil {
				t.Errorf("create session: %v", err)
				return
			}
			updated := &model.Session{
				SystemPrompt: fmt.Sprintf("session-%d", i),
				History:      []model.Message{{Role: "user", Content: "message"}},
			}
			if !store.Update(session.ID, updated) {
				t.Errorf("update session %q failed", session.ID)
				return
			}
			if _, ok := store.Get(session.ID); !ok {
				t.Errorf("get session %q failed", session.ID)
				return
			}
			if !store.Delete(session.ID) {
				t.Errorf("delete session %q failed", session.ID)
			}
		}(i)
	}
	workers.Wait()
}

func TestLockSerializesOperationsOnOneSession(t *testing.T) {
	store := NewSessionStore()
	created, err := store.Create()
	if err != nil {
		t.Fatalf("create session: %v", err)
	}
	session, unlock, ok := store.Lock(created.ID)
	if !ok {
		t.Fatal("Lock failed for an existing session")
	}

	started := make(chan struct{})
	done := make(chan bool, 1)
	go func() {
		close(started)
		done <- store.Update(created.ID, &model.Session{
			SystemPrompt: "updated",
		})
	}()
	<-started
	select {
	case <-done:
		t.Fatal("Update completed while the session lock was held")
	case <-time.After(20 * time.Millisecond):
	}

	unlock()
	if !<-done {
		t.Fatal("Update failed after the session lock was released")
	}
	if session.SystemPrompt != "updated" {
		t.Fatalf("SystemPrompt = %q, want %q", session.SystemPrompt, "updated")
	}
}
