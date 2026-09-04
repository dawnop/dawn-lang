cuda_tile.module @m {
  entry @gpt_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = constant <i32: 32> : tile<i32>
    %6 = muli %3, %5 : tile<i32>
    %7 = addi %4, %6 : tile<i32>
    %8 = constant <i32: 4096> : tile<i32>
    %9 = muli %3, %8 : tile<i32>
    %10 = constant <i32: 0> : tile<i32>
    %11 = constant <i32: 2> : tile<i32>
    %12 = constant <i32: 1> : tile<i32>
    %13 = constant <f64: 0.0> : tile<64x32xf64>
    %14, %15 = for %16 in (%10 to %11, step %12) : tile<i32> iter_values(%17 = %13, %18 = %0) -> (tile<64x32xf64>, token) {
      %19 = constant <i32: 32> : tile<i32>
      %20 = muli %16, %19 : tile<i32>
      %21 = addi %9, %20 : tile<i32>
      %22 = reshape %21 : tile<i32> -> tile<1x1xi32>
      %23 = broadcast %22 : tile<1x1xi32> -> tile<64x32xi32>
      %24 = iota : tile<64xi32>
      %25 = reshape %24 : tile<64xi32> -> tile<64x1xi32>
      %26 = broadcast %25 : tile<64x1xi32> -> tile<64x32xi32>
      %27 = constant <i32: 64> : tile<64x32xi32>
      %28 = muli %26, %27 : tile<64x32xi32>
      %29 = addi %23, %28 : tile<64x32xi32>
      %30 = iota : tile<32xi32>
      %31 = reshape %30 : tile<32xi32> -> tile<1x32xi32>
      %32 = broadcast %31 : tile<1x32xi32> -> tile<64x32xi32>
      %33 = addi %29, %32 : tile<64x32xi32>
      %34 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %35 = broadcast %34 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
      %36 = offset %35, %33 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
      %37, %38 = load_ptr_tko weak %36 token=%18 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
      %39 = constant <i32: 6144> : tile<i32>
      %40 = muli %16, %39 : tile<i32>
      %41 = addi %7, %40 : tile<i32>
      %42 = reshape %41 : tile<i32> -> tile<1x1xi32>
      %43 = broadcast %42 : tile<1x1xi32> -> tile<32x32xi32>
      %44 = iota : tile<32xi32>
      %45 = reshape %44 : tile<32xi32> -> tile<32x1xi32>
      %46 = broadcast %45 : tile<32x1xi32> -> tile<32x32xi32>
      %47 = constant <i32: 192> : tile<32x32xi32>
      %48 = muli %46, %47 : tile<32x32xi32>
      %49 = addi %43, %48 : tile<32x32xi32>
      %50 = iota : tile<32xi32>
      %51 = reshape %50 : tile<32xi32> -> tile<1x32xi32>
      %52 = broadcast %51 : tile<1x32xi32> -> tile<32x32xi32>
      %53 = addi %49, %52 : tile<32x32xi32>
      %54 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %55 = broadcast %54 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %56 = offset %55, %53 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %57, %58 = load_ptr_tko weak %56 token=%38 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %59 = mmaf %37, %57, %17 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %59, %58 : tile<64x32xf64>, token
    }
    %60 = constant <i32: 32> : tile<i32>
    %61 = muli %3, %60 : tile<i32>
    %62 = reshape %61 : tile<i32> -> tile<1x1xi32>
    %63 = broadcast %62 : tile<1x1xi32> -> tile<64x32xi32>
    %64 = iota : tile<64xi32>
    %65 = reshape %64 : tile<64xi32> -> tile<64x1xi32>
    %66 = broadcast %65 : tile<64x1xi32> -> tile<64x32xi32>
    %67 = constant <i32: 64> : tile<64x32xi32>
    %68 = muli %66, %67 : tile<64x32xi32>
    %69 = addi %63, %68 : tile<64x32xi32>
    %70 = iota : tile<32xi32>
    %71 = reshape %70 : tile<32xi32> -> tile<1x32xi32>
    %72 = broadcast %71 : tile<1x32xi32> -> tile<64x32xi32>
    %73 = addi %69, %72 : tile<64x32xi32>
    %74 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %75 = broadcast %74 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %76 = offset %75, %73 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %77 = store_ptr_tko weak %76, %14 token=%15 : tile<64x32xptr<f64>>, tile<64x32xf64> -> token
    return
  }
}
