import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider, useUser } from "@clerk/clerk-react";

const el = document.getElementById("clerk-callback");
const publishableKey = el.dataset.publishableKey;

// Clerk initializes on mount, which exchanges any __clerk_db_jwt or
// __clerk_handshake token and sets the __session cookie. Once isLoaded
// is true the exchange is complete and we can return to the callback view.
function Exchange() {
  const { isLoaded } = useUser();

  useEffect(() => {
    if (isLoaded) {
      window.location.replace("/auth/callback");
    }
  }, [isLoaded]);

  return null;
}

createRoot(el).render(
  <ClerkProvider publishableKey={publishableKey}>
    <Exchange />
  </ClerkProvider>,
);
