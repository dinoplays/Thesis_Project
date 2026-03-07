module frame_ram #(
	parameter int unsigned DATA_W = 15,
	parameter int unsigned DEPTH  = 16384,
	parameter int unsigned ADDR_W = $clog2(DEPTH)
)(
	input  wire                  clk,
	input  wire                  we,
	input  wire [ADDR_W-1:0]     wr_addr,
	input  wire [DATA_W-1:0]     wr_data,
	input  wire [ADDR_W-1:0]     rd_addr,
	output logic [DATA_W-1:0]    rd_data
);

	(* ramstyle = "M10K" *) logic [DATA_W-1:0] mem [0:DEPTH-1];

	always_ff @(posedge clk) begin
		if (we) begin
			mem[wr_addr] <= wr_data;
		end
		rd_data <= mem[rd_addr];
	end

endmodule