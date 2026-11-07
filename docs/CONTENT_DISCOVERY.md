# Internet content discovery

## Select a famous cartoon or story

When manually running the discovery workflow, choose a cartoon name such as Motu Patlu, Chhota Bheem, Tom and Jerry, Doraemon, Shinchan or Oggy, and/or choose a classic story title such as Cinderella, Alice's Adventures in Wonderland, Pinocchio, Peter Pan or The Jungle Book. The workflow searches Commons for openly licensed candidate videos matching the selected cartoon name and searches Project Gutenberg for the selected story title. "All" searches the built-in list.

A search match is not an official episode and does not prove that character rights are cleared. Famous franchise names are reference/search terms only. Official episodes remain blocked from download/publishing unless the exact rightsholder grants permission or a suitable license.

## Cartoon videos

The discovery job searches Wikimedia Commons for existing video files and accepts only metadata labels that map to CC0 1.0, CC BY 4.0, CC BY-SA 4.0 or Public Domain Mark 1.0. It records the Commons file page, direct video URL, creator metadata and license metadata.

These are **candidates only**. The Commons record may not describe all rights in the file. Before using a candidate, inspect the exact file page and the video itself. Check background music, voices, characters, logos, clips and any third-party footage. Confirm that the creator information and license apply to the exact downloadable file. Check duration and whether a 5, 7 or 10 minute source is available.

A license that permits commercial use and adaptations can still require attribution or share-alike compliance. Follow the actual license terms. The discovery script never changes the rights flags in licensed_assets.json.

## Popular story sources

The report queries Project Gutenberg's public catalog for famous classic titles (including Cinderella, Alice's Adventures in Wonderland, Pinocchio, Peter Pan, The Jungle Book and others), as well as fairy tales, fables, folk tales, classic adventures and myths/legends. It ranks returned records by catalog download count as a rough popularity signal. Download count is not proof of current virality or social-media trend status.

Project Gutenberg's public-domain distribution is based on United States copyright status. A catalog entry is not automatically clear for worldwide commercial adaptation. Check the original author, translation, edition, illustrations and applicable law for the countries where the Facebook Page will be viewed. Do not copy modern adaptations or translations unless they are separately licensed.

## Copyrighted cartoon examples

Motu Patlu and Chhota Bheem are included only as reference names because the user mentioned them. The discovery job does not download their episodes or claim they are reusable. Use them only if the exact episode is licensed for the intended commercial use or the rightsholder gives permission.

## Run

Use **Actions → Internet Cartoon & Story Discovery → Run workflow**. The job also runs weekly. It creates JSON and Markdown reports under output/ and uploads them as a GitHub Actions artifact. It does not publish to Facebook, call Buffer, or access Cloudinary.

## Approval and publishing

After review, add a candidate to licensed_assets.json using the format in LICENSED_VIDEO_SOURCING.md. Set the rights flags to true only after a human has verified the exact work, the source, commercial use, modifications, worldwide rights and all embedded elements.

The publisher is now licensed-only. It fails safely if the approved manifest is empty or incomplete. No AI-generated cartoon mode is available to the publishing workflow.