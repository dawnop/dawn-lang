cuda_tile.module @m {
  entry @gqa_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 2> : tile<i32>
    %8 = muli %6, %7 : tile<i32>
    %9 = addi %8, %1 : tile<i32>
    %10 = constant <i32: 4096> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = constant <i32: 0> : tile<i32>
    %13 = constant <i32: 2> : tile<i32>
    %14 = constant <i32: 1> : tile<i32>
    %15 = constant <f64: 0.0> : tile<64x32xf64>
    %16, %17 = for %18 in (%12 to %13, step %14) : tile<i32> iter_values(%19 = %15, %20 = %0) -> (tile<64x32xf64>, token) {
      %21 = constant <i32: 32> : tile<i32>
      %22 = muli %18, %21 : tile<i32>
      %23 = addi %11, %22 : tile<i32>
      %24 = reshape %23 : tile<i32> -> tile<1x1xi32>
      %25 = broadcast %24 : tile<1x1xi32> -> tile<64x32xi32>
      %26 = iota : tile<64xi32>
      %27 = reshape %26 : tile<64xi32> -> tile<64x1xi32>
      %28 = broadcast %27 : tile<64x1xi32> -> tile<64x32xi32>
      %29 = constant <i32: 64> : tile<64x32xi32>
      %30 = muli %28, %29 : tile<64x32xi32>
      %31 = addi %25, %30 : tile<64x32xi32>
      %32 = iota : tile<32xi32>
      %33 = reshape %32 : tile<32xi32> -> tile<1x32xi32>
      %34 = broadcast %33 : tile<1x32xi32> -> tile<64x32xi32>
      %35 = addi %31, %34 : tile<64x32xi32>
      %36 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %37 = broadcast %36 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
      %38 = offset %37, %35 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
      %39, %40 = load_ptr_tko weak %38 token=%20 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
      %41 = constant <i32: 2048> : tile<i32>
      %42 = muli %6, %41 : tile<i32>
      %43 = constant <i32: 1024> : tile<i32>
      %44 = muli %18, %43 : tile<i32>
      %45 = addi %42, %44 : tile<i32>
      %46 = reshape %45 : tile<i32> -> tile<1x1xi32>
      %47 = broadcast %46 : tile<1x1xi32> -> tile<32x32xi32>
      %48 = iota : tile<32xi32>
      %49 = reshape %48 : tile<32xi32> -> tile<32x1xi32>
      %50 = broadcast %49 : tile<32x1xi32> -> tile<32x32xi32>
      %51 = constant <i32: 32> : tile<32x32xi32>
      %52 = muli %50, %51 : tile<32x32xi32>
      %53 = addi %47, %52 : tile<32x32xi32>
      %54 = iota : tile<32xi32>
      %55 = reshape %54 : tile<32xi32> -> tile<1x32xi32>
      %56 = broadcast %55 : tile<1x32xi32> -> tile<32x32xi32>
      %57 = addi %53, %56 : tile<32x32xi32>
      %58 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %59 = broadcast %58 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %60 = offset %59, %57 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %61, %62 = load_ptr_tko weak %60 token=%40 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %63 = mmaf %39, %61, %19 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %63, %62 : tile<64x32xf64>, token
    }
    %64 = constant <i32: 2048> : tile<i32>
    %65 = muli %9, %64 : tile<i32>
    %66 = reshape %65 : tile<i32> -> tile<1x1xi32>
    %67 = broadcast %66 : tile<1x1xi32> -> tile<64x32xi32>
    %68 = iota : tile<64xi32>
    %69 = reshape %68 : tile<64xi32> -> tile<64x1xi32>
    %70 = broadcast %69 : tile<64x1xi32> -> tile<64x32xi32>
    %71 = constant <i32: 32> : tile<64x32xi32>
    %72 = muli %70, %71 : tile<64x32xi32>
    %73 = addi %67, %72 : tile<64x32xi32>
    %74 = iota : tile<32xi32>
    %75 = reshape %74 : tile<32xi32> -> tile<1x32xi32>
    %76 = broadcast %75 : tile<1x32xi32> -> tile<64x32xi32>
    %77 = addi %73, %76 : tile<64x32xi32>
    %78 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %79 = broadcast %78 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %80 = offset %79, %77 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %81 = store_ptr_tko weak %80, %16 token=%17 : tile<64x32xptr<f64>>, tile<64x32xf64> -> token
    return
  }
}
