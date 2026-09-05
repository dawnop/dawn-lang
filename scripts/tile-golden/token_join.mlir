cuda_tile.module @m {
  entry @token_join(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 64> : tile<i32>
    %7 = addi %5, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<64xi32>
    %10 = iota : tile<64xi32>
    %11 = addi %9, %10 : tile<64xi32>
    %12 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %14 = offset %13, %11 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<64xptr<f64>> -> tile<64xf64>, token
    %17 = reshape %7 : tile<i32> -> tile<1xi32>
    %18 = broadcast %17 : tile<1xi32> -> tile<64xi32>
    %19 = iota : tile<64xi32>
    %20 = addi %18, %19 : tile<64xi32>
    %21 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %22 = broadcast %21 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %23 = offset %22, %20 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %24, %25 = load_ptr_tko weak %23 token=%16 : tile<64xptr<f64>> -> tile<64xf64>, token
    %26 = addf %15, %15 rounding<nearest_even> : tile<64xf64>
    %27 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %28 = broadcast %27 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %29 = offset %28, %11 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %30 = store_ptr_tko weak %29, %26 token=%25 : tile<64xptr<f64>>, tile<64xf64> -> token
    %31 = constant <f64: 3.0> : tile<64xf64>
    %32 = mulf %24, %31 rounding<nearest_even> : tile<64xf64>
    %33 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %34 = broadcast %33 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %35 = offset %34, %20 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %36 = store_ptr_tko weak %35, %32 token=%25 : tile<64xptr<f64>>, tile<64xf64> -> token
    %37 = join_tokens %30, %36 : token
    %38 = reshape %5 : tile<i32> -> tile<1xi32>
    %39 = broadcast %38 : tile<1xi32> -> tile<128xi32>
    %40 = iota : tile<128xi32>
    %41 = addi %39, %40 : tile<128xi32>
    %42 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %43 = broadcast %42 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %44 = offset %43, %41 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %45, %46 = load_ptr_tko weak %44 token=%37 : tile<128xptr<f64>> -> tile<128xf64>, token
    %47 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %49 = offset %48, %41 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %50 = store_ptr_tko weak %49, %45 token=%46 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
