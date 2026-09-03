cuda_tile.module @m {
  entry @matmul(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 16384> : tile<i32>
    %8 = muli %1, %7 : tile<i32>
    %9 = constant <i32: 64> : tile<i32>
    %10 = muli %5, %9 : tile<i32>
    %11 = constant <f64: 0.0> : tile<64x64xf64>
    %12 = constant <i32: 0> : tile<i32>
    %13 = constant <i32: 8> : tile<i32>
    %14 = constant <i32: 1> : tile<i32>
    %15, %16 = for %17 in (%12 to %13, step %14) : tile<i32> iter_values(%18 = %11, %19 = %0) -> (tile<64x64xf64>, token) {
      %20 = constant <i32: 32> : tile<i32>
      %21 = muli %17, %20 : tile<i32>
      %22 = addi %8, %21 : tile<i32>
      %23 = reshape %22 : tile<i32> -> tile<1x1xi32>
      %24 = broadcast %23 : tile<1x1xi32> -> tile<64x32xi32>
      %25 = iota : tile<64xi32>
      %26 = reshape %25 : tile<64xi32> -> tile<64x1xi32>
      %27 = broadcast %26 : tile<64x1xi32> -> tile<64x32xi32>
      %28 = constant <i32: 256> : tile<64x32xi32>
      %29 = muli %27, %28 : tile<64x32xi32>
      %30 = addi %24, %29 : tile<64x32xi32>
      %31 = iota : tile<32xi32>
      %32 = reshape %31 : tile<32xi32> -> tile<1x32xi32>
      %33 = broadcast %32 : tile<1x32xi32> -> tile<64x32xi32>
      %34 = addi %30, %33 : tile<64x32xi32>
      %35 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %36 = broadcast %35 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
      %37 = offset %36, %34 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
      %38, %39 = load_ptr_tko weak %37 token=%19 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
      %40 = constant <i32: 8192> : tile<i32>
      %41 = muli %17, %40 : tile<i32>
      %42 = addi %10, %41 : tile<i32>
      %43 = reshape %42 : tile<i32> -> tile<1x1xi32>
      %44 = broadcast %43 : tile<1x1xi32> -> tile<32x64xi32>
      %45 = iota : tile<32xi32>
      %46 = reshape %45 : tile<32xi32> -> tile<32x1xi32>
      %47 = broadcast %46 : tile<32x1xi32> -> tile<32x64xi32>
      %48 = constant <i32: 256> : tile<32x64xi32>
      %49 = muli %47, %48 : tile<32x64xi32>
      %50 = addi %44, %49 : tile<32x64xi32>
      %51 = iota : tile<64xi32>
      %52 = reshape %51 : tile<64xi32> -> tile<1x64xi32>
      %53 = broadcast %52 : tile<1x64xi32> -> tile<32x64xi32>
      %54 = addi %50, %53 : tile<32x64xi32>
      %55 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %56 = broadcast %55 : tile<1x1xptr<f64>> -> tile<32x64xptr<f64>>
      %57 = offset %56, %54 : tile<32x64xptr<f64>>, tile<32x64xi32> -> tile<32x64xptr<f64>>
      %58, %59 = load_ptr_tko weak %57 token=%39 : tile<32x64xptr<f64>> -> tile<32x64xf64>, token
      %60 = mmaf %38, %58, %18 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
      continue %60, %59 : tile<64x64xf64>, token
    }
    %61 = constant <i32: 16384> : tile<i32>
    %62 = muli %1, %61 : tile<i32>
    %63 = addi %62, %10 : tile<i32>
    %64 = reshape %63 : tile<i32> -> tile<1x1xi32>
    %65 = broadcast %64 : tile<1x1xi32> -> tile<64x64xi32>
    %66 = iota : tile<64xi32>
    %67 = reshape %66 : tile<64xi32> -> tile<64x1xi32>
    %68 = broadcast %67 : tile<64x1xi32> -> tile<64x64xi32>
    %69 = constant <i32: 256> : tile<64x64xi32>
    %70 = muli %68, %69 : tile<64x64xi32>
    %71 = addi %65, %70 : tile<64x64xi32>
    %72 = iota : tile<64xi32>
    %73 = reshape %72 : tile<64xi32> -> tile<1x64xi32>
    %74 = broadcast %73 : tile<1x64xi32> -> tile<64x64xi32>
    %75 = addi %71, %74 : tile<64x64xi32>
    %76 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %77 = broadcast %76 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %78 = offset %77, %75 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %79 = store_ptr_tko weak %78, %15 token=%16 : tile<64x64xptr<f64>>, tile<64x64xf64> -> token
    return
  }
}
