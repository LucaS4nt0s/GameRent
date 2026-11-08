FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Variáveis do Vite são lidas no build (ver README, seção "Front-end").
ARG VITE_AUTH_PROVIDER=local
ARG VITE_ADMIN_EMAILS=
ARG VITE_COGNITO_DOMAIN=
ARG VITE_COGNITO_CLIENT_ID=
ARG VITE_COGNITO_REDIRECT_URI=
ENV VITE_AUTH_PROVIDER=$VITE_AUTH_PROVIDER     VITE_ADMIN_EMAILS=$VITE_ADMIN_EMAILS     VITE_COGNITO_DOMAIN=$VITE_COGNITO_DOMAIN     VITE_COGNITO_CLIENT_ID=$VITE_COGNITO_CLIENT_ID     VITE_COGNITO_REDIRECT_URI=$VITE_COGNITO_REDIRECT_URI

RUN npm run build

FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
