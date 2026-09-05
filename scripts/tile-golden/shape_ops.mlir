cuda_tile.module @m {
  entry @shape_ops(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 192> : tile<i32>
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
    %28 = constant <i32: 0> : tile<i32>
    %29 = constant <i32: 0> : tile<i32>
    %30 = extract %23[%28, %29] : tile<16x8xf64> -> tile<8x4xf64>
    %31 = cat %27, %30 dim = 0 : tile<8x4xf64>, tile<8x4xf64> -> tile<16x4xf64>
    %32 = reshape %7 : tile<i32> -> tile<1x1xi32>
    %33 = broadcast %32 : tile<1x1xi32> -> tile<16x4xi32>
    %34 = iota : tile<16xi32>
    %35 = reshape %34 : tile<16xi32> -> tile<16x1xi32>
    %36 = broadcast %35 : tile<16x1xi32> -> tile<16x4xi32>
    %37 = constant <i32: 4> : tile<16x4xi32>
    %38 = muli %36, %37 : tile<16x4xi32>
    %39 = addi %33, %38 : tile<16x4xi32>
    %40 = iota : tile<4xi32>
    %41 = reshape %40 : tile<4xi32> -> tile<1x4xi32>
    %42 = broadcast %41 : tile<1x4xi32> -> tile<16x4xi32>
    %43 = addi %39, %42 : tile<16x4xi32>
    %44 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %45 = broadcast %44 : tile<1x1xptr<f64>> -> tile<16x4xptr<f64>>
    %46 = offset %45, %43 : tile<16x4xptr<f64>>, tile<16x4xi32> -> tile<16x4xptr<f64>>
    %47 = store_ptr_tko weak %46, %31 token=%24 : tile<16x4xptr<f64>>, tile<16x4xf64> -> token
    %48 = reshape %5 : tile<i32> -> tile<1x1x1xi32>
    %49 = broadcast %48 : tile<1x1x1xi32> -> tile<4x4x8xi32>
    %50 = iota : tile<4xi32>
    %51 = reshape %50 : tile<4xi32> -> tile<4x1x1xi32>
    %52 = broadcast %51 : tile<4x1x1xi32> -> tile<4x4x8xi32>
    %53 = constant <i32: 32> : tile<4x4x8xi32>
    %54 = muli %52, %53 : tile<4x4x8xi32>
    %55 = addi %49, %54 : tile<4x4x8xi32>
    %56 = iota : tile<4xi32>
    %57 = reshape %56 : tile<4xi32> -> tile<1x4x1xi32>
    %58 = broadcast %57 : tile<1x4x1xi32> -> tile<4x4x8xi32>
    %59 = constant <i32: 8> : tile<4x4x8xi32>
    %60 = muli %58, %59 : tile<4x4x8xi32>
    %61 = addi %55, %60 : tile<4x4x8xi32>
    %62 = iota : tile<8xi32>
    %63 = reshape %62 : tile<8xi32> -> tile<1x1x8xi32>
    %64 = broadcast %63 : tile<1x1x8xi32> -> tile<4x4x8xi32>
    %65 = addi %61, %64 : tile<4x4x8xi32>
    %66 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1x1xptr<f64>>
    %67 = broadcast %66 : tile<1x1x1xptr<f64>> -> tile<4x4x8xptr<f64>>
    %68 = offset %67, %65 : tile<4x4x8xptr<f64>>, tile<4x4x8xi32> -> tile<4x4x8xptr<f64>>
    %69, %70 = load_ptr_tko weak %68 token=%47 : tile<4x4x8xptr<f64>> -> tile<4x4x8xf64>, token
    %71 = constant <i32: 64> : tile<i32>
    %72 = addi %7, %71 : tile<i32>
    %73 = permute %69 [1, 0, 2] : tile<4x4x8xf64> -> tile<4x4x8xf64>
    %74 = reshape %72 : tile<i32> -> tile<1x1x1xi32>
    %75 = broadcast %74 : tile<1x1x1xi32> -> tile<4x4x8xi32>
    %76 = iota : tile<4xi32>
    %77 = reshape %76 : tile<4xi32> -> tile<4x1x1xi32>
    %78 = broadcast %77 : tile<4x1x1xi32> -> tile<4x4x8xi32>
    %79 = constant <i32: 32> : tile<4x4x8xi32>
    %80 = muli %78, %79 : tile<4x4x8xi32>
    %81 = addi %75, %80 : tile<4x4x8xi32>
    %82 = iota : tile<4xi32>
    %83 = reshape %82 : tile<4xi32> -> tile<1x4x1xi32>
    %84 = broadcast %83 : tile<1x4x1xi32> -> tile<4x4x8xi32>
    %85 = constant <i32: 8> : tile<4x4x8xi32>
    %86 = muli %84, %85 : tile<4x4x8xi32>
    %87 = addi %81, %86 : tile<4x4x8xi32>
    %88 = iota : tile<8xi32>
    %89 = reshape %88 : tile<8xi32> -> tile<1x1x8xi32>
    %90 = broadcast %89 : tile<1x1x8xi32> -> tile<4x4x8xi32>
    %91 = addi %87, %90 : tile<4x4x8xi32>
    %92 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1x1xptr<f64>>
    %93 = broadcast %92 : tile<1x1x1xptr<f64>> -> tile<4x4x8xptr<f64>>
    %94 = offset %93, %91 : tile<4x4x8xptr<f64>>, tile<4x4x8xi32> -> tile<4x4x8xptr<f64>>
    %95 = store_ptr_tko weak %94, %73 token=%70 : tile<4x4x8xptr<f64>>, tile<4x4x8xf64> -> token
    return
  }
}
