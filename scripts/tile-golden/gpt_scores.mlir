cuda_tile.module @m {
  entry @gpt_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %3, %4 : tile<i32>
    %6 = constant <i32: 64> : tile<i32>
    %7 = addi %6, %5 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %9 = broadcast %8 : tile<1x1xi32> -> tile<64x32xi32>
    %10 = iota : tile<64xi32>
    %11 = reshape %10 : tile<64xi32> -> tile<64x1xi32>
    %12 = broadcast %11 : tile<64x1xi32> -> tile<64x32xi32>
    %13 = constant <i32: 192> : tile<64x32xi32>
    %14 = muli %12, %13 : tile<64x32xi32>
    %15 = addi %9, %14 : tile<64x32xi32>
    %16 = iota : tile<32xi32>
    %17 = reshape %16 : tile<32xi32> -> tile<1x32xi32>
    %18 = broadcast %17 : tile<1x32xi32> -> tile<64x32xi32>
    %19 = addi %15, %18 : tile<64x32xi32>
    %20 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %21 = broadcast %20 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %22 = offset %21, %19 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %23, %24 = load_ptr_tko weak %22 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %25 = reshape %7 : tile<i32> -> tile<1x1xi32>
    %26 = broadcast %25 : tile<1x1xi32> -> tile<32x64xi32>
    %27 = iota : tile<32xi32>
    %28 = reshape %27 : tile<32xi32> -> tile<32x1xi32>
    %29 = broadcast %28 : tile<32x1xi32> -> tile<32x64xi32>
    %30 = addi %26, %29 : tile<32x64xi32>
    %31 = iota : tile<64xi32>
    %32 = reshape %31 : tile<64xi32> -> tile<1x64xi32>
    %33 = broadcast %32 : tile<1x64xi32> -> tile<32x64xi32>
    %34 = constant <i32: 192> : tile<32x64xi32>
    %35 = muli %33, %34 : tile<32x64xi32>
    %36 = addi %30, %35 : tile<32x64xi32>
    %37 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %38 = broadcast %37 : tile<1x1xptr<f64>> -> tile<32x64xptr<f64>>
    %39 = offset %38, %36 : tile<32x64xptr<f64>>, tile<32x64xi32> -> tile<32x64xptr<f64>>
    %40, %41 = load_ptr_tko weak %39 token=%24 : tile<32x64xptr<f64>> -> tile<32x64xf64>, token
    %42 = constant <f64: 0.0> : tile<64x64xf64>
    %43 = mmaf %23, %40, %42 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
    %44 = constant <i32: 4096> : tile<i32>
    %45 = muli %3, %44 : tile<i32>
    %46 = constant <f64: 0.17677669529663687> : tile<64x64xf64>
    %47 = mulf %43, %46 rounding<nearest_even> : tile<64x64xf64>
    %48 = reshape %45 : tile<i32> -> tile<1x1xi32>
    %49 = broadcast %48 : tile<1x1xi32> -> tile<64x64xi32>
    %50 = iota : tile<64xi32>
    %51 = reshape %50 : tile<64xi32> -> tile<64x1xi32>
    %52 = broadcast %51 : tile<64x1xi32> -> tile<64x64xi32>
    %53 = constant <i32: 64> : tile<64x64xi32>
    %54 = muli %52, %53 : tile<64x64xi32>
    %55 = addi %49, %54 : tile<64x64xi32>
    %56 = iota : tile<64xi32>
    %57 = reshape %56 : tile<64xi32> -> tile<1x64xi32>
    %58 = broadcast %57 : tile<1x64xi32> -> tile<64x64xi32>
    %59 = addi %55, %58 : tile<64x64xi32>
    %60 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %61 = broadcast %60 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %62 = offset %61, %59 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %63 = store_ptr_tko weak %62, %47 token=%41 : tile<64x64xptr<f64>>, tile<64x64xf64> -> token
    return
  }
}
