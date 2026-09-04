cuda_tile.module @m {
  entry @ols_beta(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 8> : tile<i32>
    %3 = reshape %2 : tile<i32> -> tile<1xi32>
    %4 = broadcast %3 : tile<1xi32> -> tile<8xi32>
    %5 = iota : tile<8xi32>
    %6 = constant <i32: 16> : tile<8xi32>
    %7 = muli %5, %6 : tile<8xi32>
    %8 = addi %4, %7 : tile<8xi32>
    %9 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %10 = broadcast %9 : tile<1xptr<f64>> -> tile<8xptr<f64>>
    %11 = offset %10, %8 : tile<8xptr<f64>>, tile<8xi32> -> tile<8xptr<f64>>
    %12, %13 = load_ptr_tko weak %11 token=%0 : tile<8xptr<f64>> -> tile<8xf64>, token
    %14 = reshape %1 : tile<i32> -> tile<1xi32>
    %15 = broadcast %14 : tile<1xi32> -> tile<8xi32>
    %16 = iota : tile<8xi32>
    %17 = addi %15, %16 : tile<8xi32>
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<8xptr<f64>>
    %20 = offset %19, %17 : tile<8xptr<f64>>, tile<8xi32> -> tile<8xptr<f64>>
    %21 = store_ptr_tko weak %20, %12 token=%13 : tile<8xptr<f64>>, tile<8xf64> -> token
    return
  }
}
