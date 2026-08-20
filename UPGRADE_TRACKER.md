# Lighter — Upgrade Program

## Tranche 1: 100 upgrades

Completed baseline hardening: news normalization, deduplication, entity detection, Lighter market-data interfaces, signal gates, risk limits, and execution safety.

## Tranche 2: upgrades 101–200

### News intelligence
101. Multi-source feed interface
102. RSS ingestion adapter
103. Atom ingestion adapter
104. JSON feed adapter
105. Webhook ingestion interface
106. Feed health monitor
107. Source heartbeat tracking
108. Source outage detection
109. Source recovery detection
110. Per-source latency histogram
111. Article canonical URL normalization
112. URL tracking-parameter stripping
113. Language detection interface
114. Translation interface
115. Translation confidence field
116. Title/body disagreement detection
117. Author identity normalization
118. Publisher ownership metadata
119. Source independence classification
120. Syndication-chain detection
121. First-seen source tracking
122. Earliest-publication timestamp
123. Republication detection
124. Quote-origin detection
125. Primary-source preference
126. Official-announcement preference
127. Social-post source classification
128. Screenshot-only evidence flag
129. Unverifiable-claim flag
130. Source blacklist
131. Source allowlist
132. Source weighting configuration
133. Source-specific parser versioning
134. Parser failure quarantine
135. Malformed-feed quarantine
136. Content-size limits
137. HTML/script stripping
138. Encoding validation
139. MIME-type validation
140. Content hash generation
141. Semantic fingerprint generation
142. Event-cluster assignment
143. Event-cluster merge
144. Event-cluster split
145. Event chronology ordering
146. Event supersession links
147. Event correction propagation
148. Event retraction propagation
149. Event confidence decay
150. Event archival policy

### Entity and market mapping
151. Project-name alias table
152. Protocol-name alias table
153. Company-name alias table
154. Person-name alias table
155. Exchange-name alias table
156. Chain-name alias table
157. Token contract alias table
158. Lighter market-index mapping
159. Cross-chain asset mapping
160. Wrapped-asset mapping
161. Perpetual-vs-spot distinction
162. Long/short semantic normalization
163. Quote-currency normalization
164. Stablecoin classification
165. Asset-category classification
166. Governance-token classification
167. Exchange-token classification
168. L1/L2 classification
169. DeFi classification
170. Meme-token classification
171. AI-token classification
172. Infrastructure-token classification
173. Event relevance matrix
174. Direct-exposure score
175. Indirect-exposure score
176. Sector spillover score
177. Competitor spillover score
178. Narrative spillover score
179. Market-beta adjustment
180. BTC-beta adjustment
181. ETH-beta adjustment
182. Sector-beta adjustment
183. Correlation-window selection
184. Correlation confidence
185. Mapping ambiguity veto

### Event intelligence
186. Regulatory-event classifier
187. Listing-event classifier
188. Delisting-event classifier
189. Partnership-event classifier
190. Investment-event classifier
191. Funding-event classifier
192. Product-launch classifier
193. Protocol-upgrade classifier
194. Security-incident classifier
195. Exploit-event classifier
196. ETF/event classifier
197. Macro-event classifier
198. Political-statement classifier
199. Exchange-outage classifier
200. Bankruptcy/insolvency classifier

## Safety invariant
Tranche 2 expands intelligence and mapping only. Live execution remains opt-in, and no classifier may directly bypass the signal/risk pipeline.
