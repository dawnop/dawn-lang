cuda_tile.module @m {
  entry @clip(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = constant <i32: 333> : tile<64xi32>
    %11 = cmpi less_than %9, %10, signed : tile<64xi32> -> tile<64xi1>
    %12 = constant <f64: 0.0> : tile<64xf64>
    %13 = constant <f64: -1.0> : tile<64xf64>
    %14 = constant <f64: 1.0> : tile<64xf64>
    %15 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %16 = broadcast %15 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %17 = offset %16, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %18, %19 = load_ptr_tko weak %17, %11, %12 token=%0 : tile<64xptr<f64>>, tile<64xi1>, tile<64xf64> -> tile<64xf64>, token
    %20 = maxf %18, %13 : tile<64xf64>
    %21 = minf %20, %14 : tile<64xf64>
    %22 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %23 = broadcast %22 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %24 = offset %23, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %25 = store_ptr_tko weak %24, %21, %11 token=%19 : tile<64xptr<f64>>, tile<64xf64>, tile<64xi1> -> token
    return
  }
}
