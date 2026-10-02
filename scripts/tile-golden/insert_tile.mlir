cuda_tile.module @m {
  entry @insert_tile(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 256> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1x1xi32>
    %9 = broadcast %8 : tile<1x1xi32> -> tile<16x8xi32>
    %10 = iota : tile<16xi32>
    %11 = reshape %10 : tile<16xi32> -> tile<16x1xi32>
    %12 = broadcast %11 : tile<16x1xi32> -> tile<16x8xi32>
    %13 = constant <i32: 8> : tile<16x8xi32>
    %14 = muli %12, %13 : tile<16x8xi32>
    %15 = addi %9, %14 : tile<16x8xi32>
    %16 = iota : tile<8xi32>
    %17 = reshape %16 : tile<8xi32> -> tile<1x8xi32>
    %18 = broadcast %17 : tile<1x8xi32> -> tile<16x8xi32>
    %19 = addi %15, %18 : tile<16x8xi32>
    %20 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %21 = broadcast %20 : tile<1x1xptr<f64>> -> tile<16x8xptr<f64>>
    %22 = offset %21, %19 : tile<16x8xptr<f64>>, tile<16x8xi32> -> tile<16x8xptr<f64>>
    %23, %24 = load_ptr_tko weak %22 token=%0 : tile<16x8xptr<f64>> -> tile<16x8xf64>, token
    %25 = constant <i32: 1> : tile<i32>
    %26 = constant <i32: 0> : tile<i32>
    %27 = extract %23[%25, %26] : tile<16x8xf64> -> tile<8x4xf64>
    %28 = constant <i32: 1> : tile<i32>
    %29 = constant <i32: 0> : tile<i32>
    %30 = insert %27, %23[%28, %29] : tile<8x4xf64>, tile<16x8xf64>
    %31 = reshape %7 : tile<i32> -> tile<1x1xi32>
    %32 = broadcast %31 : tile<1x1xi32> -> tile<16x8xi32>
    %33 = iota : tile<16xi32>
    %34 = reshape %33 : tile<16xi32> -> tile<16x1xi32>
    %35 = broadcast %34 : tile<16x1xi32> -> tile<16x8xi32>
    %36 = constant <i32: 8> : tile<16x8xi32>
    %37 = muli %35, %36 : tile<16x8xi32>
    %38 = addi %32, %37 : tile<16x8xi32>
    %39 = iota : tile<8xi32>
    %40 = reshape %39 : tile<8xi32> -> tile<1x8xi32>
    %41 = broadcast %40 : tile<1x8xi32> -> tile<16x8xi32>
    %42 = addi %38, %41 : tile<16x8xi32>
    %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %44 = broadcast %43 : tile<1x1xptr<f64>> -> tile<16x8xptr<f64>>
    %45 = offset %44, %42 : tile<16x8xptr<f64>>, tile<16x8xi32> -> tile<16x8xptr<f64>>
    %46 = store_ptr_tko weak %45, %30 token=%24 : tile<16x8xptr<f64>>, tile<16x8xf64> -> token
    %47 = constant <i32: 128> : tile<i32>
    %48 = addi %7, %47 : tile<i32>
    %49 = constant <i32: 0> : tile<i32>
    %50 = constant <i32: 1> : tile<i32>
    %51 = insert %27, %23[%49, %50] : tile<8x4xf64>, tile<16x8xf64>
    %52 = reshape %48 : tile<i32> -> tile<1x1xi32>
    %53 = broadcast %52 : tile<1x1xi32> -> tile<16x8xi32>
    %54 = iota : tile<16xi32>
    %55 = reshape %54 : tile<16xi32> -> tile<16x1xi32>
    %56 = broadcast %55 : tile<16x1xi32> -> tile<16x8xi32>
    %57 = constant <i32: 8> : tile<16x8xi32>
    %58 = muli %56, %57 : tile<16x8xi32>
    %59 = addi %53, %58 : tile<16x8xi32>
    %60 = iota : tile<8xi32>
    %61 = reshape %60 : tile<8xi32> -> tile<1x8xi32>
    %62 = broadcast %61 : tile<1x8xi32> -> tile<16x8xi32>
    %63 = addi %59, %62 : tile<16x8xi32>
    %64 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %65 = broadcast %64 : tile<1x1xptr<f64>> -> tile<16x8xptr<f64>>
    %66 = offset %65, %63 : tile<16x8xptr<f64>>, tile<16x8xi32> -> tile<16x8xptr<f64>>
    %67 = store_ptr_tko weak %66, %51 token=%46 : tile<16x8xptr<f64>>, tile<16x8xf64> -> token
    return
  }
}
