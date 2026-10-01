import { useEffect, useState } from "react";
import { campaignsApi } from "../api/campaigns";
import type { AffiliateDestination as Destination } from "../types";

const message = (value: Destination) =>
  value.affiliateValidationStatus === "VALID"
    ? "Link de afiliado válido para atribuição elegível. Produto correspondente."
    : value.affiliateValidationStatus === "INVALID"
      ? value.failureCode === "AFFILIATE_ITEM_MISMATCH"
        ? "O link aponta para outro produto."
        : "Este link não é um destino afiliado válido."
      : value.affiliateValidationStatus === "UNVERIFIED"
        ? "Não foi possível verificar o produto deste link."
        : "Abra o Gerador de Links ou a Barra de Afiliados do Mercado Livre, gere o link deste produto e cole aqui.";

export function AffiliateDestination({ candidateId, readOnly = false, secondaryAction = false }: { candidateId: string; readOnly?: boolean; secondaryAction?: boolean }) {
  const [data, setData] = useState<Destination | null>(null),
    [url, setUrl] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    campaignsApi
      .affiliateDestination(candidateId)
      .then((value) => {
        setData(value);
        setUrl(value.affiliateUrl ?? "");
      })
      .catch(() => setError("Não foi possível carregar o destino comercial."));
  }, [candidateId]);
  const validate = async () => {
    setBusy(true);
    setError("");
    try {
      const value = await campaignsApi.configureAffiliateDestination(
        candidateId,
        url,
      );
      setData(value);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Não foi possível validar o link.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="affiliate-destination">
      <div>
        <small>Produto</small>
        <b>{data?.productTitle ?? "Produto ainda não vinculado"}</b>
      </div>
      <div>
        <small>Anúncio</small>
        {data?.sourcePermalink ? (
          <a href={data.sourcePermalink} target="_blank" rel="noreferrer">
            Abrir anúncio vinculado
          </a>
        ) : (
          <span>Não informado</span>
        )}
      </div>
      {!readOnly && <>
        <label>
          Link de afiliado
          <input
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="Cole o link gerado oficialmente"
          />
        </label>
        <button
          type="button"
          className={secondaryAction ? "secondary-button" : "primary-button"}
          disabled={busy || !url.trim()}
          onClick={validate}
        >
          {busy ? "Validando…" : "Validar link"}
        </button>
      </>}
      {data && (
        <p
          role="status"
          className={
            "affiliate-result " + data.affiliateValidationStatus.toLowerCase()
          }
        >
          {message(data)}
        </p>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <small>
        A validação não garante remuneração; a atribuição depende das regras do
        programa e da elegibilidade da compra.
      </small>
    </div>
  );
}
