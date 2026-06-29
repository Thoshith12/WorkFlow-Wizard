FROM quay.io/keycloak/keycloak:24.0.1 as builder

# Configure database vendor
ENV KC_DB=postgres

# If you have custom providers or themes, you can uncomment these:
# COPY ./providers/*.jar /opt/keycloak/providers/
# COPY ./themes/ /opt/keycloak/themes/

RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:24.0.1
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# Dev mode execution
ENTRYPOINT ["/opt/keycloak/bin/kc.sh", "start-dev"]
