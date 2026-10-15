import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider, SignIn, useUser } from "@clerk/clerk-react";

const el = document.getElementById("clerk-sign-in");
const publishableKey = el.dataset.publishableKey;

function App() {
  const { isLoaded, isSignedIn } = useUser();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      window.location.replace("/auth/callback");
    }
  }, [isLoaded, isSignedIn]);

  if (!isLoaded || isSignedIn) return null;

  return <SignIn forceRedirectUrl="/auth/callback" />;
}

createRoot(el).render(
  <ClerkProvider publishableKey={publishableKey}>
    <App />
  </ClerkProvider>,
);
