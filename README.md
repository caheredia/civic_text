# civic_text
Parse text from PDF files

## Extract Transform Load (ETL)
Ideally PDFs would be converted from PDF to text. Can LLMs determine the type of document (minutes versus Agenda) from the text alone? Or would a better starting point be the raw PDFs (not parsed text)? Then perhaps the LLM could reason the context. Would a python only solution (parsed text) lose the document-type context? 

Another solution: For cost efficient parsing, could we use Batch processing with AWS Bedrock?


# Resources
* [The AWS Nonprofit Credit Program](https://aws.amazon.com/government-education/nonprofits/nonprofit-credit-program/)
	- Providing up to $5,000 in AWS Promotional Credit to nonprofits around the world
* [AWS pricing for nonprofits](https://www.techsoup.org/amazon-web-services)
